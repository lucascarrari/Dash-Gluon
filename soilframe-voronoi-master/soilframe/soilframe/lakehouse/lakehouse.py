from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd


class LakehouseManager:
    """Gerenciador da arquitetura de Data Lakehouse (Bronze, Prata, Ouro) para o SoilFrame."""

    def __init__(self, base_dir: str | Path = "data/lakehouse") -> None:
        self.base_dir = Path(base_dir)
        self.bronze_dir = self.base_dir / "bronze"
        self.prata_dir = self.base_dir / "prata"
        self.ouro_dir = self.base_dir / "ouro"
        self._garantir_diretorios()

    def _garantir_diretorios(self) -> None:
        """Cria as pastas físicas das três camadas se não existirem."""
        self.bronze_dir.mkdir(parents=True, exist_ok=True)
        self.prata_dir.mkdir(parents=True, exist_ok=True)
        self.ouro_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # 1. CAMADA BRONZE (RAW / DADOS BRUTOS INGERIDOS)
    # =========================================================================
    def salvar_bronze(
        self,
        df_raw: pd.DataFrame,
        uf: str,
        ano: int | str,
        metadados: dict[str, Any] | None = None,
    ) -> Path:
        """Armazena o payload bruto baixado com rastreabilidade e timestamp."""
        uf_upper = uf.upper()
        pasta_destino = self.bronze_dir / f"uf={uf_upper}" / f"ano={ano}"
        pasta_destino.mkdir(parents=True, exist_ok=True)

        caminho_parquet = pasta_destino / "raw_aquacrop.parquet"
        df_raw.to_parquet(caminho_parquet, index=False)

        info_meta = {
            "uf": uf_upper,
            "ano": str(ano),
            "camada": "bronze",
            "registros_ingeridos": len(df_raw),
            "colunas": list(df_raw.columns),
            "data_ingestao_utc": datetime.now(timezone.utc).isoformat(),
            **(metadados or {}),
        }
        (pasta_destino / "metadata.json").write_text(
            json.dumps(info_meta, indent=2, default=str), encoding="utf-8"
        )
        return caminho_parquet

    def existe_em_bronze(self, uf: str, ano: int | str) -> bool:
        """Verifica se a UF e ano já foram ingeridos na Camada Bronze."""
        return (self.bronze_dir / f"uf={uf.upper()}" / f"ano={ano}" / "raw_aquacrop.parquet").exists()

    # =========================================================================
    # 2. CAMADA PRATA (SILVER / ESTRUTURADO, LIMPO E VALIDADO)
    # =========================================================================
    def promover_para_prata(self, uf: str, ano: int | str) -> pd.DataFrame:
        """Lê os dados da Camada Bronze, executa validação de tipos, regras físicas e deduplicação."""
        uf_upper = uf.upper()
        origem = self.bronze_dir / f"uf={uf_upper}" / f"ano={ano}" / "raw_aquacrop.parquet"
        if not origem.exists():
            raise FileNotFoundError(f"Dados brutos não encontrados na camada Bronze para UF={uf_upper}, ano={ano}")

        df = pd.read_parquet(origem)

        # 1. Deduplicação em chave primária natural (célula e data)
        if "cell_id" in df.columns and "data" in df.columns:
            df = df.drop_duplicates(subset=["cell_id", "data"]).copy()

        # 2. Tipagem e saneamento básico
        df["cell_id"] = df["cell_id"].astype(int)
        df["municipio"] = df["municipio"].astype(str)
        df["uf"] = uf_upper
        df["data"] = pd.to_datetime(df["data"]).dt.strftime("%Y-%m-%d")

        # 3. Tratamento de limites físicos agroclimáticos
        if "tmax_c" in df.columns and "tmin_c" in df.columns:
            # Garante que Tmin <= Tmax
            tmin_real = np.minimum(df["tmin_c"], df["tmax_c"])
            tmax_real = np.maximum(df["tmin_c"], df["tmax_c"])
            df["tmin_c"] = tmin_real
            df["tmax_c"] = tmax_real

        if "precipitacao_mm" in df.columns:
            df["precipitacao_mm"] = df["precipitacao_mm"].clip(lower=0.0)

        if "et0_mm" in df.columns:
            df["et0_mm"] = df["et0_mm"].clip(lower=0.0)

        if "radiacao_solar_mj_m2" in df.columns:
            df["radiacao_solar_mj_m2"] = df["radiacao_solar_mj_m2"].clip(lower=0.0)

        if "vento_10m_ms" in df.columns:
            df["vento_10m_ms"] = df["vento_10m_ms"].clip(lower=0.0)

        # Ordenação consistente
        df = df.sort_values(["cell_id", "data"]).reset_index(drop=True)

        # Salva na Camada Prata
        pasta_destino = self.prata_dir / f"uf={uf_upper}" / f"ano={ano}"
        pasta_destino.mkdir(parents=True, exist_ok=True)
        caminho_prata = pasta_destino / "clima_aquacrop_prata.parquet"
        df.to_parquet(caminho_prata, index=False)

        info_meta = {
            "uf": uf_upper,
            "ano": ano,
            "camada": "prata",
            "registros_validados": len(df),
            "celulas_unicas": df["cell_id"].nunique(),
            "data_processamento_utc": datetime.now(timezone.utc).isoformat(),
        }
        (pasta_destino / "metadata.json").write_text(
            json.dumps(info_meta, indent=2, default=str), encoding="utf-8"
        )
        return df

    def existe_em_prata(self, uf: str, ano: int) -> bool:
        """Verifica se a UF e ano já foram validados na Camada Prata."""
        return (self.prata_dir / f"uf={uf.upper()}" / f"ano={ano}" / "clima_aquacrop_prata.parquet").exists()

    # =========================================================================
    # 3. CAMADA OURO (GOLD / ENRIQUECIDO, INDICADORES E MODEL-READY)
    # =========================================================================
    def promover_para_ouro(
        self,
        uf: str,
        ano: int | str,
        gerar_arquivos_aquacrop: bool = True,
    ) -> pd.DataFrame:
        """Lê da Camada Prata, calcula indicadores agronômicos avançados e exporta arquivos FAO."""
        uf_upper = uf.upper()
        origem = self.prata_dir / f"uf={uf_upper}" / f"ano={ano}" / "clima_aquacrop_prata.parquet"
        if not origem.exists():
            # Tenta promover da Bronze para Prata primeiro
            self.promover_para_prata(uf_upper, ano)

        df = pd.read_parquet(origem)

        # 1. Atributos Temporais e Sazonais
        dt = pd.to_datetime(df["data"])
        df["mes"] = dt.dt.month
        df["dia_ano"] = dt.dt.dayofyear
        # Estação do ano no Hemisfério Sul (1=Verão, 2=Outono, 3=Inverno, 4=Primavera)
        df["estacao_ano"] = np.select(
            [(df["mes"].isin([12, 1, 2])), (df["mes"].isin([3, 4, 5])), (df["mes"].isin([6, 7, 8]))],
            [1, 2, 3],
            default=4,
        )

        # 2. Indicadores Agroclimáticos Derivados do AquaCrop
        if "tmax_c" in df.columns and "tmin_c" in df.columns:
            df["amplitude_termica"] = np.round(df["tmax_c"] - df["tmin_c"], 2)

        if "precipitacao_mm" in df.columns and "et0_mm" in df.columns:
            balanco = np.round(df["precipitacao_mm"] - df["et0_mm"], 2)
            df["balanco_hidrico_diario"] = balanco
            df["razao_p_et0"] = np.round(
                (df["precipitacao_mm"] / np.maximum(df["et0_mm"], 0.1)).clip(upper=10.0), 2
            )

            # Classificação Agronômica Oficial do Estresse Hídrico
            condicoes = [
                balanco < -3.0,
                (balanco >= -3.0) & (balanco < 0.0),
                balanco >= 0.0,
            ]
            rotulos = ["Deficit_Severo", "Deficit_Moderado", "Adequado"]
            df["classe_deficit_hidrico"] = np.select(condicoes, rotulos, default="Adequado")

        # Salva na Camada Ouro
        pasta_destino = self.ouro_dir / f"uf={uf_upper}" / f"ano={ano}"
        pasta_destino.mkdir(parents=True, exist_ok=True)
        caminho_ouro = pasta_destino / "aquacrop_ouro.parquet"
        df.to_parquet(caminho_ouro, index=False)

        # Gera arquivos FAO AquaCrop (.CLI, .TMP, .PLU, .ETo)
        arquivos_fao = []
        if gerar_arquivos_aquacrop and not df.empty:
            pasta_aquacrop = pasta_destino / "aquacrop_files"
            arquivos_fao = self._gerar_arquivos_fao_aquacrop(df, pasta_aquacrop, ano, uf_upper)

        info_meta = {
            "uf": uf_upper,
            "ano": str(ano),
            "camada": "ouro",
            "registros_curados": len(df),
            "celulas_unicas": df["cell_id"].nunique(),
            "arquivos_aquacrop_gerados": [str(p.name) for p in arquivos_fao],
            "data_curadoria_utc": datetime.now(timezone.utc).isoformat(),
        }
        (pasta_destino / "metadata.json").write_text(
            json.dumps(info_meta, indent=2, default=str), encoding="utf-8"
        )
        return df

    def existe_em_ouro(self, uf: str, ano: int | str) -> bool:
        """Verifica se a UF e ano já foram concluídos na Camada Ouro."""
        return (self.ouro_dir / f"uf={uf.upper()}" / f"ano={ano}" / "aquacrop_ouro.parquet").exists()

    def _gerar_arquivos_fao_aquacrop(
        self,
        df: pd.DataFrame,
        destino: Path,
        ano: int | str,
        uf: str,
    ) -> list[Path]:
        """Gera os 4 arquivos oficiais do AquaCrop (.CLI, .TMP, .PLU, .ETo) para a célula representativa."""
        destino.mkdir(parents=True, exist_ok=True)
        primeira_celula = df["cell_id"].iloc[0]
        alvos = df[df["cell_id"] == primeira_celula]

        mun_nome = str(alvos["municipio"].iloc[0]).replace(" ", "_")
        dt_primeiro = pd.to_datetime(alvos["data"].iloc[0])
        ano_inicio = dt_primeiro.year if pd.notna(dt_primeiro) else 2022
        prefix = f"{mun_nome}_{uf}_{primeira_celula}_{ano}"

        # 1. Temperatura (.TMP)
        f_tmp = destino / f"{prefix}.TMP"
        with open(f_tmp, "w", encoding="utf-8") as f:
            f.write(f"{mun_nome} ({uf}) - ERA5-Land Temperature\n")
            f.write("   1 : Daily records (1=Daily, 2=10-daily, 3=Monthly)\n")
            f.write("   1 : First day of record (1..31)\n")
            f.write("   1 : First month of record (1..12)\n")
            f.write(f"{ano_inicio} : First year of record (1901..2100)\n\n")
            f.write("  Tmin (C)   Tmax (C)\n")
            f.write("========================\n")
            for _, r in alvos.iterrows():
                f.write(f"{r['tmin_c']:10.1f} {r['tmax_c']:10.1f}\n")

        # 2. Chuva (.PLU)
        f_plu = destino / f"{prefix}.PLU"
        with open(f_plu, "w", encoding="utf-8") as f:
            f.write(f"{mun_nome} ({uf}) - ERA5-Land Precipitation\n")
            f.write("   1 : Daily records (1=Daily, 2=10-daily, 3=Monthly)\n")
            f.write("   1 : First day of record (1..31)\n")
            f.write("   1 : First month of record (1..12)\n")
            f.write(f"{ano_inicio} : First year of record (1901..2100)\n\n")
            f.write(" Total Rain (mm)\n")
            f.write("========================\n")
            for _, r in alvos.iterrows():
                f.write(f"{r['precipitacao_mm']:10.1f}\n")

        # 3. Evapotranspiração de Referência (.ETo)
        f_eto = destino / f"{prefix}.ETo"
        with open(f_eto, "w", encoding="utf-8") as f:
            f.write(f"{mun_nome} ({uf}) - ERA5-Land Reference ET (FAO-56)\n")
            f.write("   1 : Daily records (1=Daily, 2=10-daily, 3=Monthly)\n")
            f.write("   1 : First day of record (1..31)\n")
            f.write("   1 : First month of record (1..12)\n")
            f.write(f"{ano_inicio} : First year of record (1901..2100)\n\n")
            f.write("   ETo (mm/day)\n")
            f.write("========================\n")
            for _, r in alvos.iterrows():
                f.write(f"{r['et0_mm']:10.2f}\n")

        # 4. Arquivo Mestre (.CLI)
        f_cli = destino / f"{prefix}.CLI"
        with open(f_cli, "w", encoding="utf-8") as f:
            f.write(f"{mun_nome} ({uf}) - Climate Dataset AquaCrop FAO\n")
            f.write(" 7.0 : AquaCrop Version (August 2022)\n")
            f.write(f"{f_tmp.name}\n")
            f.write(f"{f_eto.name}\n")
            f.write(f"{f_plu.name}\n")
            f.write("MaunaLoa.CO2\n")

        return [f_cli, f_tmp, f_plu, f_eto]

    # =========================================================================
    # 4. INGESTÃO DE DADOS JÁ BAIXADOS (EX: MINAS GERAIS)
    # =========================================================================
    def ingerir_dados_existentes(self, caminho_arquivo: str | Path, uf: str, ano: int = 2024) -> None:
        """Permite plugar dados já baixados anteriormente (ex: MG) diretamente no Lakehouse."""
        p = Path(caminho_arquivo)
        if not p.exists():
            return
        df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
        self.salvar_bronze(df, uf=uf, ano=ano, metadados={"origem": "ingestao_existente"})
        self.promover_para_prata(uf=uf, ano=ano)
        self.promover_para_ouro(uf=uf, ano=ano, gerar_arquivos_aquacrop=True)

    # =========================================================================
    # 5. CONSOLIDAÇÃO NACIONAL E RESUMO DO LAKEHOUSE
    # =========================================================================
    def consolidar_nacional(self, ano: int | str = 2024) -> pd.DataFrame:
        """Consolida todas as partições disponíveis na Camada Ouro em uma base nacional única."""
        particoes = list(self.ouro_dir.glob(f"uf=*/ano={ano}/aquacrop_ouro.parquet"))
        if not particoes:
            raise FileNotFoundError(f"Nenhuma partição encontrada na camada Ouro para o ano {ano}.")

        dfs = [pd.read_parquet(p) for p in particoes]
        df_nacional = pd.concat(dfs, ignore_index=True)
        df_nacional = df_nacional.sort_values(["uf", "cell_id", "data"]).reset_index(drop=True)

        caminho_nacional = self.ouro_dir / f"brasil_aquacrop_{ano}.parquet"
        df_nacional.to_parquet(caminho_nacional, index=False)
        return df_nacional

    def resumo_lakehouse(self) -> pd.DataFrame:
        """Retorna uma tabela de auditoria com status e volumetria das três camadas."""
        ufs = set()
        for p in self.base_dir.glob("*/*"):
            if "uf=" in p.name:
                ufs.add(p.name.replace("uf=", ""))

        linhas = []
        for uf in sorted(ufs):
            tem_b = any(self.bronze_dir.glob(f"uf={uf}/*/*.parquet"))
            tem_p = any(self.prata_dir.glob(f"uf={uf}/*/*.parquet"))
            tem_o = any(self.ouro_dir.glob(f"uf={uf}/*/*.parquet"))

            linhas_ouro = 0
            tamanho_mb = 0.0
            particoes_ouro = list(self.ouro_dir.glob(f"uf={uf}/*/*.parquet"))
            if particoes_ouro:
                df_o = pd.read_parquet(particoes_ouro[0])
                linhas_ouro = len(df_o)
                tamanho_mb = sum(p.stat().st_size for p in particoes_ouro) / (1024 * 1024)

            linhas.append({
                "uf": uf,
                "bronze": "OK" if tem_b else "Pendente",
                "prata": "OK" if tem_p else "Pendente",
                "ouro": "OK" if tem_o else "Pendente",
                "linhas_ouro": linhas_ouro,
                "tamanho_mb": round(tamanho_mb, 2),
            })

        return pd.DataFrame(linhas)
