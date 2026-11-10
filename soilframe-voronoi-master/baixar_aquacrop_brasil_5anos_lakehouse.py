#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download Nacional de Variáveis AquaCrop (ERA5-Land) em Janela de 5 Anos (2020 a 2024).

Executa o pipeline completo de Data Lakehouse para todo o Brasil (27 UFs):
  - Anos Contemplados: 2020, 2021, 2022, 2023 e 2024 (1.827 dias consecutivos).
  - Camada Bronze: Ingestão bruta dos lotes da API Open-Meteo ERA5-Land (5 anos diários).
  - Camada Prata: Dados limpos, deduplicados e com saneamento de limites físicos.
  - Camada Ouro: Dados enriquecidos com balanço hídrico diário (P - ET0), classes
                agronômicas de déficit hídrico e arquivos FAO AquaCrop (.CLI, .TMP, .PLU, .ETo).
  - Base Nacional Ouro: Consolidação de todas as UFs em 'brasil_aquacrop_2020_2024.parquet'.

Uso:
    python baixar_aquacrop_brasil_5anos_lakehouse.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
import pandas as pd

# Garante importação do soilframe
sys.path.insert(0, str(Path(__file__).resolve().parent / "soilframe"))

from soilframe import FonteERA5LandVoronoi, LakehouseManager

import socket
socket.setdefaulttimeout(60)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# Todas as 27 Unidades Federativas do Brasil
UFS_BRASIL_27 = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
    "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
    "RO", "RR", "RS", "SC", "SE", "SP", "TO"
]


def main():
    print("=" * 85)
    print(" SOILFRAME: DOWNLOAD NACIONAL ERA5-LAND AQUACROP (JANELA DE 5 ANOS: 2020 A 2024)")
    print(" Arquitetura: Data Lakehouse (Bronze, Prata e Ouro) com Células de Voronoi")
    print(" Cobertura: Todo o Brasil (27 Unidades Federativas)")
    print(" Anos Contemplados: 2020, 2021, 2022, 2023 e 2024 (5 Anos Completos)")
    print(" Período: 2020-01-01 a 2024-12-31 (1.827 dias consecutivos por município)")
    print("=" * 85)

    t_inicio = time.time()

    periodo_tag = "2020_2024"
    data_inicio = "2020-01-01"
    data_fim = "2024-12-31"
    celulas_por_uf = 5  # Top células municipais de Voronoi por UF
    lakehouse_dir = Path("soilframe/data/lakehouse")
    lakehouse = LakehouseManager(base_dir=lakehouse_dir)

    print("\n[1] Configuração do Lakehouse:")
    print(f"    - Diretório: {lakehouse_dir.resolve()}")
    print(f"    - Anos Contemplados: 2020, 2021, 2022, 2023, 2024")
    print(f"    - Janela: {data_inicio} até {data_fim} (5 anos completos = 1.827 dias)")
    print(f"    - Células Voronoi por UF: {celulas_por_uf} municípios representativos")
    print(f"    - Total de UFs: {len(UFS_BRASIL_27)}")

    relatorio_ufs = []
    total_registros_geral = 0

    print("\n[2] Iniciando processamento das UFs nas 3 camadas...")

    for idx, uf in enumerate(UFS_BRASIL_27, 1):
        # 1. Resumabilidade: se já existe na Camada Ouro para o período, reaproveita
        if lakehouse.existe_em_ouro(uf, periodo_tag):
            print(f"[{idx:02d}/{len(UFS_BRASIL_27)}] UF={uf}: Já processada na Camada Ouro ({periodo_tag}). Carregando do cache...")
            df_ouro = pd.read_parquet(lakehouse.ouro_dir / f"uf={uf}" / f"ano={periodo_tag}" / "aquacrop_ouro.parquet")
            relatorio_ufs.append({"uf": uf, "status": "cache_ouro", "linhas": len(df_ouro)})
            total_registros_geral += len(df_ouro)
            continue

        print(f"\n[{idx:02d}/{len(UFS_BRASIL_27)}] Processando UF: {uf} (5 Anos: 2020 a 2024)...")

        fonte = FonteERA5LandVoronoi(
            uf=uf,
            ano=periodo_tag,
            data_inicio=data_inicio,
            data_fim=data_fim,
            limite_celulas=celulas_por_uf,
            salvar_disco=False,
        )

        try:
            # 2. Download e Ingestão na Camada BRONZE
            df_raw = fonte.extrair(tamanho_lote=25)
            lakehouse.salvar_bronze(
                df_raw,
                uf=uf,
                ano=periodo_tag,
                metadados={
                    "janela": f"{data_inicio} a {data_fim}",
                    "anos_contemplados": [2020, 2021, 2022, 2023, 2024],
                    "dias_totais": 1827,
                    "fonte": "Open-Meteo ERA5-Land Archive",
                },
            )

            # 3. Limpeza e Validação na Camada PRATA
            lakehouse.promover_para_prata(uf=uf, ano=periodo_tag)

            # 4. Enriquecimento e Arquivos FAO na Camada OURO
            df_ouro = lakehouse.promover_para_ouro(
                uf=uf,
                ano=periodo_tag,
                gerar_arquivos_aquacrop=True,
            )

            n_linhas = len(df_ouro)
            total_registros_geral += n_linhas
            relatorio_ufs.append({"uf": uf, "status": "sucesso", "linhas": n_linhas})
            print(f"  -> Concluído {uf}: {n_linhas:,} registros diários (Bronze, Prata e Ouro OK).")

            # Pausa preventiva entre requisições para estabilidade de conexão
            time.sleep(2.0)

        except Exception as e:
            print(f"  [Erro] Falha ao processar {uf}: {e}")
            relatorio_ufs.append({"uf": uf, "status": f"erro: {e}", "linhas": 0})

    # 5. Consolidação Nacional na Camada Ouro (5 Anos)
    print("\n" + "=" * 85)
    print(" [3] CONSOLIDANDO CAMADA OURO NACIONAL (5 ANOS: 2020 A 2024)")
    print("=" * 85)
    try:
        df_nacional = lakehouse.consolidar_nacional(ano=periodo_tag)
        caminho_nacional = lakehouse.ouro_dir / f"brasil_aquacrop_{periodo_tag}.parquet"
        print("Base Nacional Ouro consolidada com sucesso:")
        print(f"  - Arquivo: {caminho_nacional.resolve()}")
        print(f"  - Total de registros diários: {len(df_nacional):,}")
        print(f"  - UFs presentes: {df_nacional['uf'].nunique()} UFs")
        print(f"  - Intervalo de datas: {df_nacional['data'].min()} até {df_nacional['data'].max()}")
        print(f"  - Tamanho no disco: {caminho_nacional.stat().st_size / (1024 * 1024):.2f} MB")
    except Exception as e:
        print(f"Erro na consolidação nacional: {e}")
        df_nacional = pd.DataFrame()

    # 6. Auditoria Final do Lakehouse
    print("\n" + "=" * 85)
    print(" AUDITORIA DAS CAMADAS DO LAKEHOUSE (JANELA DE 5 ANOS: 2020 A 2024)")
    print("=" * 85)
    linhas_auditoria = []
    for r in relatorio_ufs:
        uf_name = r["uf"]
        p_ouro = lakehouse.ouro_dir / f"uf={uf_name}" / f"ano={periodo_tag}" / "aquacrop_ouro.parquet"
        tam_mb = p_ouro.stat().st_size / (1024 * 1024) if p_ouro.exists() else 0.0
        linhas_auditoria.append({
            "UF": uf_name,
            "Bronze": "OK" if r["linhas"] > 0 else "Falha",
            "Prata": "OK" if r["linhas"] > 0 else "Falha",
            "Ouro": "OK" if r["linhas"] > 0 else "Falha",
            "Registros (5 Anos)": f"{r['linhas']:,}",
            "Tamanho MB": round(tam_mb, 2),
        })
    df_audit = pd.DataFrame(linhas_auditoria)
    print(df_audit.to_string(index=False))

    tempo_total = time.time() - t_inicio
    print("\n" + "=" * 85)
    print(" DOWNLOAD E PROCESSAMENTO DE 5 ANOS FINALIZADOS COM SUCESSO!")
    print("=" * 85)
    print(f"Tempo total de execução: {tempo_total:.1f} segundos")
    print(f"Total geral de observações climáticas diárias: {total_registros_geral:,}")
    print(f"Estrutura física do Lakehouse:")
    print(f"  - Bronze: {lakehouse.bronze_dir.resolve()}")
    print(f"  - Prata:  {lakehouse.prata_dir.resolve()}")
    print(f"  - Ouro:   {lakehouse.ouro_dir.resolve()}")
    print("=" * 85)


if __name__ == "__main__":
    main()
