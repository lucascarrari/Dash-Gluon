import unittest
import numpy as np
import pandas as pd
from soil_analysis.config import TIPOS_NAO_PEDOLOGICOS_GRAFICOS
from soil_analysis.comparison import (
    calcular_balanco_climatico,
    resumir_indicadores_por_tipo,
)

class ResumoIndicadoresTests(unittest.TestCase):
    def test_pondera_precipitacao_e_swi_e_reporta_cobertura(self):
        nao_pedologico = next(iter(TIPOS_NAO_PEDOLOGICOS_GRAFICOS))
        dados = pd.DataFrame(
            {
                "tipo_solo_principal": [
                    "Solo A", "Solo A", "Solo A", "Solo B", nao_pedologico
                ],
                "area_km2": [1.0, 3.0, 4.0, 2.0, 10.0],
                "estado_sigla": ["AA", "BB", "BB", "CC", "DD"],
                "regiao_nome": ["R1", "R2", "R2", "R2", "R3"],
                "precipitacao_anual_media_mm": [100.0, 200.0, np.nan, 300.0, 999.0],
                "precipitacao_anualizada_media_mm": [
                    108.3, 216.6, np.nan, 325.0, 999.0
                ],
                "dias_medios_observados": [338.0, 338.0, np.nan, 338.0, 366.0],
                "swi_010_media": [20.0, 60.0, 40.0, np.nan, 99.0],
                "lst_celsius_tipo_media": [30.0, 30.0, 30.0, 35.0, 99.0],
                "porosidade_estimada_media": [40.0, np.nan, np.nan, 50.0, 99.0],
            }
        )

        resumo = resumir_indicadores_por_tipo(dados).set_index("tipo_solo_principal")

        self.assertEqual(set(resumo.index), {"Solo A", "Solo B"})
        solo_a = resumo.loc["Solo A"]
        self.assertAlmostEqual(solo_a["area_km2"], 8.0)
        self.assertAlmostEqual(solo_a["precipitacao_media_ponderada_mm"], 175.0)
        self.assertAlmostEqual(
            solo_a["precipitacao_anualizada_media_ponderada_mm"], 189.525
        )
        self.assertAlmostEqual(solo_a["dias_precipitacao_media_ponderada"], 338.0)
        self.assertAlmostEqual(
            solo_a["cobertura_temporal_precipitacao_pct"], 100 * 338 / 366
        )
        self.assertAlmostEqual(solo_a["area_com_precipitacao_km2"], 4.0)
        self.assertAlmostEqual(solo_a["cobertura_precipitacao_pct"], 50.0)
        self.assertAlmostEqual(solo_a["swi_010_media_ponderada"], 45.0)
        self.assertAlmostEqual(solo_a["cobertura_swi_pct"], 100.0)
        self.assertAlmostEqual(solo_a["lst_celsius_media"], 30.0)
        self.assertAlmostEqual(solo_a["cobertura_lst_pct"], 100.0)
        self.assertAlmostEqual(solo_a["porosidade_estimada_media"], 40.0)
        self.assertAlmostEqual(solo_a["cobertura_porosidade_pct"], 12.5)


class BalancoClimaticoTests(unittest.TestCase):
    def test_calcula_balanco_e_evitar_divisao_por_zero(self):
        resumo = pd.DataFrame(
            {
                "tipo_solo_principal": ["Solo A", "Solo B", "Solo C"],
                "precipitacao_media_ponderada_mm": [1500.0, 1000.0, 800.0],
                "precipitacao_anualizada_media_ponderada_mm": [1600.0, 1000.0, 900.0],
            }
        )
        et0 = pd.DataFrame(
            {
                "tipo_solo_principal": ["Solo A", "Solo B", "Solo D"],
                "et0_anual_media_mm": [1200.0, 0.0, 900.0],
                "pixels_et0": [4, 2, 1],
            }
        )

        resultado = calcular_balanco_climatico(resumo, et0).set_index(
            "tipo_solo_principal"
        )

        self.assertEqual(set(resultado.index), {"Solo A", "Solo B", "Solo C"})
        self.assertAlmostEqual(resultado.loc["Solo A", "balanco_climatico_mm"], 400.0)
        self.assertAlmostEqual(resultado.loc["Solo A", "razao_p_et0"], 4 / 3)
        self.assertAlmostEqual(resultado.loc["Solo B", "balanco_climatico_mm"], 1000.0)
        self.assertTrue(pd.isna(resultado.loc["Solo B", "razao_p_et0"]))
        self.assertTrue(pd.isna(resultado.loc["Solo C", "balanco_climatico_mm"]))
        self.assertTrue(pd.isna(resultado.loc["Solo C", "razao_p_et0"]))
        self.assertTrue(
            (
                resultado["precipitacao_usada_balanco"]
                == "precipitacao_anualizada_media_ponderada_mm"
            ).all()
        )


if __name__ == "__main__":
    unittest.main()
