from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable
import numpy as np
import pandas as pd

from ..core.data_sources import FonteDados
from ..core.dataset import Dataset
from .voronoi import EstrategiaDownloadVoronoi

# Variáveis oficiais exigidas pelo modelo FAO AquaCrop
VARIAVEIS_AQUACROP = {
    "temperature_2m_max": "tmax_c",
    "temperature_2m_min": "tmin_c",
    "temperature_2m_mean": "tmean_c",
    "precipitation_sum": "precipitacao_mm",
    "et0_fao_evapotranspiration": "et0_mm",
    "shortwave_radiation_sum": "radiacao_solar_mj_m2",
    "wind_speed_10m_max": "vento_10m_ms",
}

OPEN_METEO_ERA5_URL = "https://archive-api.open-meteo.com/v1/era5"


class FonteERA5LandVoronoi(FonteDados):
    """Fonte de dados meteorológicos ERA5-Land para AquaCrop guiada pelo Agro-Voronoi."""

    def __init__(
        self,
        uf: str | Iterable[str] = "MG",
        ano: int = 2024,
        data_inicio: str | None = None,
        data_fim: str | None = None,
        estrategia: EstrategiaDownloadVoronoi | None = None,
        limite_celulas: int | None = None,
        pasta_destino: str | Path = "data/era5land",
        salvar_disco: bool = True,
        nome: str = "ERA5Land_AquaCrop_Voronoi",
        schema: dict[str, Any] | None = None,
    ) -> None:
        default_schema = {
            "cell_id": int,
            "municipio": str,
            "uf": str,
            "data": str,
            "tmax_c": float,
            "tmin_c": float,
            "precipitacao_mm": float,
            "et0_mm": float,
        }
        super().__init__(nome=nome, schema=schema or default_schema)
        self.uf = uf
        self.ano = ano
        ano_int = int(str(ano)[:4]) if str(ano)[:4].isdigit() else 2024
        self.data_inicio = data_inicio or f"{ano_int}-01-01"
        self.data_fim = data_fim or f"{ano_int}-12-31"
        self.estrategia = estrategia or EstrategiaDownloadVoronoi()
        self.limite_celulas = limite_celulas
        self.pasta_destino = Path(pasta_destino)
        self.salvar_disco = salvar_disco
        self._dados_extraidos: pd.DataFrame | None = None

    def _obter_celulas_voronoi(self) -> pd.DataFrame:
        """Filtra as células de Voronoi para a região de interesse (ex: MG)."""
        plano = self.estrategia.planejar(uf=self.uf)
        tabela = plano.tabela.copy()
        if self.limite_celulas:
            tabela = tabela.head(self.limite_celulas)
        return tabela

    def _baixar_lote_coordenadas(
        self,
        lote_celulas: list[dict[str, Any]],
        max_tentativas: int = 5,
    ) -> list[dict[str, Any]]:

        """Baixa as variáveis diárias do ERA5-Land para um lote de coordenadas."""
        lats = [f"{c['lat']:.4f}" for c in lote_celulas]
        lons = [f"{c['lon']:.4f}" for c in lote_celulas]
        vars_str = ",".join(VARIAVEIS_AQUACROP.keys())

        url = (
            f"{OPEN_METEO_ERA5_URL}?"
            f"latitude={','.join(lats)}&"
            f"longitude={','.join(lons)}&"
            f"start_date={self.data_inicio}&"
            f"end_date={self.data_fim}&"
            f"daily={vars_str}&"
            f"timezone=America%2FSao_Paulo"
        )

        for tentativa in range(1, max_tentativas + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "soilframe/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    conteudo = json.loads(resp.read().decode("utf-8"))
                    
                # Se lote tiver 1 item, API pode retornar dicionário direto em vez de lista
                if isinstance(conteudo, dict):
                    lista_respostas = [conteudo]
                else:
                    lista_respostas = conteudo

                linhas_lote = []
                for cel, resp_cel in zip(lote_celulas, lista_respostas):
                    daily = resp_cel.get("daily", {})
                    datas = daily.get("time", [])
                    num_dias = len(datas)
                    if num_dias == 0:
                        continue

                    for i in range(num_dias):
                        registro = {
                            "cell_id": int(cel["id"]),
                            "municipio": cel["nome"],
                            "uf": cel["uf"],
                            "lat": cel["lat"],
                            "lon": cel["lon"],
                            "area_km2": cel["area_km2"],
                            "data": datas[i],
                        }
                        for var_era5, col_nome in VARIAVEIS_AQUACROP.items():
                            val = daily.get(var_era5, [None])[i]
                            registro[col_nome] = round(float(val), 2) if val is not None else np.nan
                        linhas_lote.append(registro)
                return linhas_lote
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    espera = 15.0 * tentativa
                    time.sleep(espera)
                elif tentativa == max_tentativas:
                    print(f"[Aviso] Falha HTTP {e.code} ao baixar lote ({len(lote_celulas)} células): {e}")
                    return []
                else:
                    time.sleep(2.0 * tentativa)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                if tentativa == max_tentativas:
                    print(f"[Aviso] Falha de conexão ao baixar lote ({len(lote_celulas)} células): {e}")
                    return []
                time.sleep(2.0 * tentativa)
        return []

    def extrair(self, tamanho_lote: int = 25, max_workers: int = 2) -> pd.DataFrame:

        """Executa o download de todas as células de Voronoi da região."""
        if self._dados_extraidos is not None:
            return self._dados_extraidos

        tabela_celulas = self._obter_celulas_voronoi()
        celulas_dict = tabela_celulas.to_dict(orient="records")
        n_total = len(celulas_dict)
        print(f"Iniciando download ERA5-Land AquaCrop para {n_total} células de Voronoi ({self.uf})...")
        print(f"Janela temporal: {self.data_inicio} até {self.data_fim} (Ano {self.ano})")

        # Divide em lotes para minimizar número de chamadas HTTP
        lotes = [celulas_dict[i:i + tamanho_lote] for i in range(0, n_total, tamanho_lote)]
        print(f"Total de requisições em lote: {len(lotes)} (tamanho={tamanho_lote}, workers={max_workers})")

        todas_linhas = []
        for i, lote in enumerate(lotes, 1):
            linhas = self._baixar_lote_coordenadas(lote)
            todas_linhas.extend(linhas)
            if i % 5 == 0 or i == len(lotes):
                print(f"Progresso: {i}/{len(lotes)} lotes concluídos ({len(todas_linhas):,} registros diários)...")
            if i < len(lotes):
                time.sleep(1.2)


        df = pd.DataFrame(todas_linhas)
        if df.empty:
            raise RuntimeError("Nenhum dado retornado do download ERA5-Land.")

        # Ordenação consistente
        df = df.sort_values(["cell_id", "data"]).reset_index(drop=True)
        self._dados_extraidos = df

        if self.salvar_disco:
            self._salvar_arquivos(df)

        return df

    def _salvar_arquivos(self, df: pd.DataFrame) -> None:
        """Salva a base consolidada em Parquet e CSV e gera arquivos AquaCrop."""
        self.pasta_destino.mkdir(parents=True, exist_ok=True)
        uf_tag = self.uf if isinstance(self.uf, str) else "_".join(self.uf)
        base_name = f"era5land_aquacrop_{uf_tag.lower()}_{self.ano}"

        caminho_parquet = self.pasta_destino / f"{base_name}.parquet"
        caminho_csv = self.pasta_destino / f"{base_name}.csv"

        df.to_parquet(caminho_parquet, index=False)
        df.to_csv(caminho_csv, index=False)
        print(f"[Sucesso] Arquivos salvos:")
        print(f"  - Parquet: {caminho_parquet}")
        print(f"  - CSV:     {caminho_csv}")

    def exportar_arquivos_aquacrop(
        self,
        celula_id: int | None = None,
        pasta_saida: str | Path | None = None,
    ) -> list[Path]:
        """Gera os arquivos climáticos oficiais no formato FAO AquaCrop (.CLI, .TMP, .PLU, .ETo)."""
        df = self.extrair()
        destino = Path(pasta_saida) if pasta_saida else self.pasta_destino / "aquacrop_files"
        destino.mkdir(parents=True, exist_ok=True)

        if celula_id is not None:
            alvos = df[df["cell_id"] == celula_id]
        else:
            # Pega o primeiro município como padrão ou o mais agrícola
            primeiro_id = df["cell_id"].iloc[0]
            alvos = df[df["cell_id"] == primeiro_id]

        mun_nome = alvos["municipio"].iloc[0].replace(" ", "_")
        c_id = alvos["cell_id"].iloc[0]
        prefix = f"{mun_nome}_{c_id}_{self.ano}"
        dt_min = pd.to_datetime(alvos["data"]).min()
        ano_ref = dt_min.year if pd.notna(dt_min) else (int(str(self.ano)[:4]) if str(self.ano)[:4].isdigit() else 2022)

        # 1. Arquivo de Temperatura (.TMP)
        f_tmp = destino / f"{prefix}.TMP"
        with open(f_tmp, "w", encoding="utf-8") as f:
            f.write(f"{mun_nome} - ERA5-Land Temperature\n")
            f.write("   1 : Daily records (1=Daily, 2=10-daily, 3=Monthly)\n")
            f.write("   1 : First day of record (1..31)\n")
            f.write("   1 : First month of record (1..12)\n")
            f.write(f"{ano_ref} : First year of record (1901..2100)\n\n")
            f.write("  Tmin (C)   Tmax (C)\n")
            f.write("========================\n")
            for _, r in alvos.iterrows():
                f.write(f"{r['tmin_c']:10.1f} {r['tmax_c']:10.1f}\n")

        # 2. Arquivo de Chuva (.PLU)
        f_plu = destino / f"{prefix}.PLU"
        with open(f_plu, "w", encoding="utf-8") as f:
            f.write(f"{mun_nome} - ERA5-Land Precipitation\n")
            f.write("   1 : Daily records (1=Daily, 2=10-daily, 3=Monthly)\n")
            f.write("   1 : First day of record (1..31)\n")
            f.write("   1 : First month of record (1..12)\n")
            f.write(f"{ano_ref} : First year of record (1901..2100)\n\n")
            f.write(" Total Rain (mm)\n")
            f.write("========================\n")
            for _, r in alvos.iterrows():
                f.write(f"{r['precipitacao_mm']:10.1f}\n")

        # 3. Arquivo de Evapotranspiração (.ETo)
        f_eto = destino / f"{prefix}.ETo"
        with open(f_eto, "w", encoding="utf-8") as f:
            f.write(f"{mun_nome} - ERA5-Land Reference ET (FAO-56)\n")
            f.write("   1 : Daily records (1=Daily, 2=10-daily, 3=Monthly)\n")
            f.write("   1 : First day of record (1..31)\n")
            f.write("   1 : First month of record (1..12)\n")
            f.write(f"{ano_ref} : First year of record (1901..2100)\n\n")
            f.write("   ETo (mm/day)\n")
            f.write("========================\n")
            for _, r in alvos.iterrows():
                f.write(f"{r['et0_mm']:10.2f}\n")

        # 4. Arquivo Mestre (.CLI)
        f_cli = destino / f"{prefix}.CLI"
        with open(f_cli, "w", encoding="utf-8") as f:
            f.write(f"{mun_nome} (MG) - Climate Dataset AquaCrop FAO\n")
            f.write(" 7.0 : AquaCrop Version (August 2022)\n")
            f.write(f"{f_tmp.name}\n")
            f.write(f"{f_eto.name}\n")
            f.write(f"{f_plu.name}\n")
            f.write("MaunaLoa.CO2\n")

        return [f_cli, f_tmp, f_plu, f_eto]

    def dataset(self) -> Dataset:
        df = self.extrair()
        self.validar_schema(df)
        metadados = {
            "source": self.nome,
            "source_type": self.__class__.__name__,
            "uf": self.uf,
            "ano": self.ano,
            "janela": f"{self.data_inicio} a {self.data_fim}",
            "variaveis_aquacrop": list(VARIAVEIS_AQUACROP.values()),
            "total_celulas": df["cell_id"].nunique(),
            "total_registros": len(df),
        }
        return Dataset(df, metadata=metadados)
