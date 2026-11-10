import tempfile
import unittest
import pandas as pd
import geopandas as gpd
from pathlib import Path
from unittest.mock import patch
from shapely.geometry import box
from soil_analysis.precipitation import (
    METODO_ANUALIZACAO_PRECIPITACAO,
    carregar_precipitacao_observada,
    vincular_precipitacao_por_municipio,
)

class PrecipitacaoAnualizadaTests(unittest.TestCase):
    def setUp(self):
        datas_338 = pd.date_range('2024-01-01', periods=338, freq='D')
        datas_366 = pd.date_range('2024-01-01', '2024-12-31', freq='D')
        parcial = pd.DataFrame(
            {
                'codigoestacao': 'A',
                'data': datas_338,
                'chuva_mm': 1.0,
                'Codigo_Municipio_IBGE': 1100015,
                'Municipio_IBGE': 'Municipio A',
                'UF_IBGE': 'RO',
            }
        )
        completo = pd.DataFrame(
            {
                'codigoestacao': 'B',
                'data': datas_366,
                'chuva_mm': 2.0,
                'Codigo_Municipio_IBGE': 1100023,
                'Municipio_IBGE': 'Municipio B',
                'UF_IBGE': 'RO',
            }
        )
        self.dados = pd.concat([parcial, completo], ignore_index=True)

    def _carregar_csv_temporario(self):
        temporario = tempfile.TemporaryDirectory()
        path = Path(temporario.name) / 'chuva.csv'
        self.dados.to_csv(path, sep=';', encoding='utf-8-sig', index=False)
        return temporario, carregar_precipitacao_observada(path)

    def test_anualiza_2024_com_338_dias_e_preserva_ano_completo(self):
        temporario, tabelas = self._carregar_csv_temporario()
        self.addCleanup(temporario.cleanup)
        estacao_ano, estacao_media, municipio, uf = tabelas

        por_estacao_ano = estacao_ano.set_index('codigoestacao')
        self.assertEqual(por_estacao_ano.loc['A', 'dias_observados'], 338)
        self.assertEqual(por_estacao_ano.loc['A', 'dias_no_ano'], 366)
        self.assertAlmostEqual(por_estacao_ano.loc['A', 'chuva_total_mm'], 338.0)
        self.assertAlmostEqual(por_estacao_ano.loc['A', 'precipitacao_anualizada_mm'], 366.0)
        self.assertEqual(por_estacao_ano.loc['A', 'precipitacao_anualizada_metodo'], METODO_ANUALIZACAO_PRECIPITACAO)

        self.assertEqual(por_estacao_ano.loc['B', 'dias_observados'], 366)
        self.assertEqual(por_estacao_ano.loc['B', 'dias_no_ano'], 366)
        self.assertAlmostEqual(por_estacao_ano.loc['B', 'chuva_total_mm'], 732.0)
        self.assertAlmostEqual(por_estacao_ano.loc['B', 'precipitacao_anualizada_mm'], 732.0)

        por_estacao = estacao_media.set_index('codigoestacao')
        self.assertAlmostEqual(por_estacao.loc['A', 'precipitacao_media_anual_mm'], 338.0)
        self.assertAlmostEqual(por_estacao.loc['A', 'precipitacao_anualizada_media_mm'], 366.0)

        por_municipio = municipio.set_index('Codigo_Municipio_IBGE')
        self.assertAlmostEqual(por_municipio.loc[1100015, 'precipitacao_anual_media_mm'], 338.0)
        self.assertAlmostEqual(por_municipio.loc[1100015, 'precipitacao_anualizada_media_mm'], 366.0)
        self.assertAlmostEqual(por_municipio.loc[1100023, 'precipitacao_anualizada_media_mm'], 732.0)

        ro = uf.set_index('UF_IBGE').loc['RO']
        self.assertAlmostEqual(ro['precipitacao_anual_media_mm'], 535.0)
        self.assertAlmostEqual(ro['precipitacao_anualizada_media_mm'], 549.0)
        self.assertEqual(ro['precipitacao_anualizada_metodo'], METODO_ANUALIZACAO_PRECIPITACAO)

    def test_propaga_precipitacao_anualizada_ao_gdf(self):
        temporario, tabelas = self._carregar_csv_temporario()
        self.addCleanup(temporario.cleanup)
        municipio = tabelas[2]

        geometria = box(-62.0, -12.0, -61.9, -11.9)
        municipios_geobr = gpd.GeoDataFrame(
            {
                'Codigo_Municipio_IBGE': [1100015],
                'Municipio_IBGE_geobr': ['Municipio A'],
                'UF_IBGE': ['RO'],
                'estado_nome_geobr': ['Rondonia'],
                'regiao_nome_municipio': ['Norte'],
            },
            geometry=[geometria],
            crs='EPSG:4326',
        )
        solos = gpd.GeoDataFrame(
            {'estado_sigla': ['RO']},
            geometry=[geometria],
            crs='EPSG:4326',
        )

        with patch(
            'soil_analysis.precipitation.carregar_municipios_geobr',
            return_value=municipios_geobr,
        ):
            resultado = vincular_precipitacao_por_municipio(solos, municipio)

        self.assertAlmostEqual(resultado.loc[0, 'precipitacao_anual_media_mm'], 338.0)
        self.assertAlmostEqual(resultado.loc[0, 'precipitacao_anualizada_media_mm'], 366.0)
        self.assertEqual(
            resultado.loc[0, 'precipitacao_anualizada_metodo'],
            METODO_ANUALIZACAO_PRECIPITACAO,
        )


if __name__ == '__main__':
    unittest.main()
