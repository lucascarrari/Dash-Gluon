from __future__ import annotations

import time
from typing import Any, Iterable
import pandas as pd

from ..core.dataset import Dataset
from ..core.pipeline import Pipeline
from ..download.era5land import FonteERA5LandVoronoi
from ..lakehouse.lakehouse import LakehouseManager

TODAS_UFS_BRASIL = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
    "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO",
    "RR", "RS", "SC", "SE", "SP", "TO"  # 26 UFs (MG excluído)
]


class PipelineAquaCropLakehouse(Pipeline):
    """Pipeline executivo para download e orquestração do Lakehouse (Bronze, Prata, Ouro) das UFs do Brasil."""

    name = "pipeline_aquacrop_lakehouse"
    version = "1.0.0"

    @classmethod
    def parameters(cls) -> dict[str, Any]:
        return {
            "ufs": {"type": "array", "required": False, "default": TODAS_UFS_BRASIL},
            "ano": {"type": "integer", "required": False, "default": 2024},
            "data_inicio": {"type": "string", "required": False, "default": "2024-01-01"},
            "data_fim": {"type": "string", "required": False, "default": "2024-12-31"},
            "celulas_por_uf": {"type": "integer", "required": False, "default": 10},
            "lakehouse_dir": {"type": "string", "required": False, "default": "data/lakehouse"},
            "ingerir_mg_existente": {"type": "boolean", "required": False, "default": True},
        }

    def rodar(self, parameters: dict[str, Any] | None = None) -> Dataset:
        params = self.validate_parameters(parameters or {})
        ufs_alvo: list[str] = params.get("ufs", TODAS_UFS_BRASIL)
        ano: int = params.get("ano", 2024)
        data_ini: str = params.get("data_inicio", f"{ano}-01-01")
        data_fim: str = params.get("data_fim", f"{ano}-12-31")
        limite_cel: int | None = params.get("celulas_por_uf", 10)
        lakehouse_dir: str = params.get("lakehouse_dir", "data/lakehouse")
        ingerir_mg: bool = params.get("ingerir_mg_existente", True)

        lakehouse = LakehouseManager(base_dir=lakehouse_dir)

        # 1. Se solicitado, ingere MG existente diretamente no Lakehouse
        if ingerir_mg:
            caminhos_mg = [
                "soilframe/data/era5land/era5land_aquacrop_mg_2024.parquet",
                "data/era5land/era5land_aquacrop_mg_2024.parquet",
            ]
            for c_mg in caminhos_mg:
                try:
                    lakehouse.ingerir_dados_existentes(c_mg, uf="MG", ano=ano)
                    break
                except Exception:
                    pass

        print(f"=== INICIANDO PIPELINE LAKEHOUSE ERA5-LAND AQUACROP (Ano {ano}) ===")
        print(f"Camadas ativas: Bronze (Raw) -> Prata (Validado) -> Ouro (AquaCrop Enriquecido)")
        print(f"Total de UFs para download: {len(ufs_alvo)} (excluindo MG)")
        print(f"Células de Voronoi por UF: {'Todas' if limite_cel is None else limite_cel}")

        relatorio_ufs = []
        total_registros_geral = 0

        for idx, uf in enumerate(ufs_alvo, 1):
            uf_clean = uf.upper()
            if uf_clean == "MG":
                continue  # Garante exclusão de MG conforme instrução

            # Resumabilidade: se já está na Camada Ouro, reaproveita
            if lakehouse.existe_em_ouro(uf_clean, ano):
                print(f"[{idx}/{len(ufs_alvo)}] UF={uf_clean} já processada na Camada Ouro. Pulando download.")
                df_ouro = pd.read_parquet(lakehouse.ouro_dir / f"uf={uf_clean}" / f"ano={ano}" / "aquacrop_ouro.parquet")
                relatorio_ufs.append({"uf": uf_clean, "status": "cache_ouro", "linhas": len(df_ouro)})
                total_registros_geral += len(df_ouro)
                continue

            print(f"\n[{idx}/{len(ufs_alvo)}] Processando UF: {uf_clean}...")
            fonte = FonteERA5LandVoronoi(
                uf=uf_clean,
                ano=ano,
                data_inicio=data_ini,
                data_fim=data_fim,
                limite_celulas=limite_cel,
                salvar_disco=False,  # Será salvo estruturadamente no Lakehouse
            )

            try:
                # 1. Download e Ingestão na Camada BRONZE
                df_raw = fonte.extrair(tamanho_lote=25)
                lakehouse.salvar_bronze(
                    df_raw,
                    uf=uf_clean,
                    ano=ano,
                    metadados={"janela": f"{data_ini} a {data_fim}", "fonte": "Open-Meteo ERA5-Land"},
                )

                # 2. Transformação e Validação na Camada PRATA
                lakehouse.promover_para_prata(uf=uf_clean, ano=ano)

                # 3. Enriquecimento e Indicadores na Camada OURO
                df_ouro = lakehouse.promover_para_ouro(
                    uf=uf_clean,
                    ano=ano,
                    gerar_arquivos_aquacrop=True,
                )

                n_linhas = len(df_ouro)
                total_registros_geral += n_linhas
                relatorio_ufs.append({"uf": uf_clean, "status": "sucesso", "linhas": n_linhas})
                print(f"  -> Concluído {uf_clean}: {n_linhas:,} registros promovidos para Bronze, Prata e Ouro.")

                # Pausa preventiva entre UFs para respeitar a taxa da API
                time.sleep(1.0)

            except Exception as e:
                print(f"  [Erro] Falha ao processar {uf_clean}: {e}")
                relatorio_ufs.append({"uf": uf_clean, "status": f"erro: {e}", "linhas": 0})

        # Consolidação Nacional na Camada Ouro
        print("\n=== CONSOLIDANDO CAMADA OURO NACIONAL ===")
        try:
            df_nacional = lakehouse.consolidar_nacional(ano=ano)
            print(f"Base Nacional Ouro consolidada com sucesso:")
            print(f"  - Total de registros: {len(df_nacional):,}")
            print(f"  - Total de UFs: {df_nacional['uf'].nunique()}")
            print(f"  - Arquivo: {lakehouse.ouro_dir / f'brasil_aquacrop_{ano}.parquet'}")
        except Exception as e:
            print(f"Aviso na consolidação nacional: {e}")
            df_nacional = pd.DataFrame(relatorio_ufs)

        return Dataset(
            df_nacional,
            metadata={
                "pipeline": self.name,
                "version": self.version,
                "ano": ano,
                "ufs_processadas": len(ufs_alvo),
                "total_registros": total_registros_geral,
                "lakehouse_dir": str(lakehouse.base_dir),
            },
        )
