import unittest
import numpy as np
import pandas as pd
from soilframe import (
    Dataset,
    Registry,
    EstrategiaDownloadVoronoi,
    EstrategiaDownloadUniforme,
    FonteSentinelVoronoi,
    PlanoDownload,
    PipelineDownloadSentinel,
)
from soilframe.download import (
    albers,
    albers_inv,
    bytes_km2,
    p_visivel,
    PIXELS_M,
)


class DownloadVoronoiTests(unittest.TestCase):
    def test_registry_expoe_pipeline_download_sentinel(self):
        registry = Registry()
        pipelines = [item["name"] for item in registry.list_pipelines()]
        self.assertIn("pipeline_download_sentinel", pipelines)

        pipe = registry.get_pipeline("pipeline_download_sentinel")
        self.assertIsInstance(pipe, PipelineDownloadSentinel)
        self.assertIn("meta_cobertura", pipe.parameters())
        self.assertIn("perfil_bandas", pipe.parameters())

    def test_albers_projection_and_inverse(self):
        lons = np.array([-54.0, -45.79, -50.92])
        lats = np.array([-12.0, -12.09, -17.79])
        x, y = albers(lons, lats)
        lon_recup, lat_recup = albers_inv(x, y)
        np.testing.assert_allclose(lon_recup, lons, atol=1e-4)
        np.testing.assert_allclose(lat_recup, lats, atol=1e-4)

    def test_bytes_km2_perfis_espectrais(self):
        b_12 = bytes_km2(10, perfil="l2a_12")
        b_ndvi = bytes_km2(10, perfil="ndvi_scl")
        self.assertGreater(b_12, 0)
        self.assertGreater(b_ndvi, 0)
        # ndvi_scl a 10m (B4, B8 a 10m uint16 + SCL a 20m uint8 = 42.5k) é ~38% das 12 bandas (111.1k)
        razao = b_ndvi / b_12
        self.assertAlmostEqual(razao, 0.3825, delta=0.01)

        # Resolução mais grossa deve consumir estritamente menos bytes por km²
        self.assertLess(bytes_km2(100, perfil="ndvi_scl"), bytes_km2(10, perfil="ndvi_scl"))
        self.assertLess(bytes_km2(1000, perfil="ndvi_scl"), bytes_km2(100, perfil="ndvi_scl"))

    def test_visibilidade_pureza_limites_e_monotonia(self):
        # Talhão grande em relação ao pixel -> visibilidade 1.0
        self.assertAlmostEqual(float(p_visivel(500.0, 10.0)), 1.0, places=2)
        # Talhão muito menor que o pixel -> visibilidade 0.0
        self.assertAlmostEqual(float(p_visivel(5.0, 1000.0)), 0.0, places=2)
        # Monotonia: com mesmo tamanho de pixel, talhão maior tem probabilidade >=
        p1 = p_visivel(50.0, 30.0)
        p2 = p_visivel(100.0, 30.0)
        self.assertGreaterEqual(p2, p1)

    def test_estrategia_voronoi_otimiza_por_meta_e_orcamento(self):
        est = EstrategiaDownloadVoronoi(perfil_bandas="ndvi_scl")
        
        # Otimização por meta de 90%
        ch_meta, gb_meta, ca_meta, _ = est.otimizar(meta_cobertura=0.90, objetivo="area")
        self.assertGreaterEqual(ca_meta, 0.90)
        self.assertGreater(gb_meta, 0.0)
        self.assertEqual(len(ch_meta), len(est.carregar_dados()["v_info"]))

        # Otimização por orçamento de 2 GB
        ch_orc, gb_orc, ca_orc, _ = est.otimizar(orcamento_gb=2.0, objetivo="area")
        self.assertLessEqual(gb_orc, 2.01)
        self.assertGreater(ca_orc, 0.50)

    def test_estrategia_voronoi_gera_economia_substancial_vs_uniforme(self):
        est_voronoi = EstrategiaDownloadVoronoi(perfil_bandas="ndvi_scl")
        plano_voronoi = est_voronoi.planejar(meta_cobertura=0.99, objetivo="area")

        est_uniforme = EstrategiaDownloadUniforme(pixel_m=30, perfil_bandas="ndvi_scl")
        plano_uniforme = est_uniforme.planejar()

        gb_voronoi = plano_voronoi.metricas["gb_por_data"]
        gb_uniforme = plano_uniforme.metricas["gb_por_data"]

        # A alocação Voronoi otimizada deve gastar substancialmente menos GB
        self.assertLess(gb_voronoi, gb_uniforme)
        self.assertGreater(plano_voronoi.metricas["fator_reducao"], 1.5)
        self.assertGreater(plano_voronoi.metricas["fator_reducao_10m"], 5.0)

    def test_estrategia_voronoi_filtro_geografico(self):
        est = EstrategiaDownloadVoronoi(perfil_bandas="ndvi_scl")
        dados = est.carregar_dados()
        ufs_presentes = {c.get("u") for c in dados["v_info"] if c.get("u")}
        
        # Filtra para uma UF que sabemos existir nos dados
        uf_teste = "MT" if "MT" in ufs_presentes else list(ufs_presentes)[0]
        plano = est.planejar(meta_cobertura=0.95, uf=uf_teste)
        self.assertTrue((plano.tabela["uf"] == uf_teste).all())
        self.assertGreater(len(plano.tabela), 0)

    def test_plano_download_to_dataset_e_resumos(self):
        est = EstrategiaDownloadVoronoi(perfil_bandas="ndvi_scl")
        plano = est.planejar(meta_cobertura=0.95)

        dataset = plano.to_dataset()
        self.assertIsInstance(dataset, Dataset)
        self.assertEqual(dataset.metadata["source_type"], "download_plan")
        self.assertIn("fator_reducao", dataset.metadata)

        regional = plano.resumo_regional()
        self.assertIsInstance(regional, pd.DataFrame)
        self.assertIn("gb_total", regional.columns)
        self.assertIn("pixel_mediano_m", regional.columns)

        texto = plano.resumo_executivo()
        self.assertIn("Resumo Executivo", texto)
        self.assertIn("Fator de economia", texto)

    def test_fonte_sentinel_voronoi_contrato(self):
        fonte = FonteSentinelVoronoi(meta_cobertura=0.95, perfil_bandas="ndvi_scl")
        df = fonte.extrair()
        self.assertIsInstance(df, pd.DataFrame)
        self.assertIn("pixel_m", df.columns)
        self.assertIn("volume_mb", df.columns)

        dataset = fonte.dataset()
        self.assertIsInstance(dataset, Dataset)
        self.assertEqual(dataset.metadata["source"], "Sentinel2_AgroVoronoi")

        reqs = fonte.gerar_requisicoes_stac()
        self.assertEqual(len(reqs), len(df))
        self.assertIn("resolucao_alvo_m", reqs[0])
        self.assertIn("assets_solicitados", reqs[0])

    def test_pipeline_download_sentinel_rodar(self):
        pipe = PipelineDownloadSentinel()
        resultado = pipe.rodar({
            "meta_cobertura": 0.95,
            "perfil_bandas": "ndvi_scl",
            "objetivo": "area",
        })
        self.assertIsInstance(resultado, Dataset)
        self.assertEqual(resultado.metadata["pipeline"], "pipeline_download_sentinel")
        self.assertIn("gb_por_data", resultado.metadata)
        self.assertGreater(len(resultado.data), 0)

    def test_pipeline_aquacrop_era5_discovery_e_contrato(self):
        from soilframe import PipelineAquaCropERA5, FonteERA5LandVoronoi
        registry = Registry()
        pipe = registry.get_pipeline("pipeline_aquacrop_era5")
        self.assertIsInstance(pipe, PipelineAquaCropERA5)
        self.assertIn("uf", pipe.parameters())
        self.assertIn("ano", pipe.parameters())

        # Teste com fonte e dados salvos em disco
        fonte = FonteERA5LandVoronoi(uf="MG", ano=2024, limite_celulas=2, salvar_disco=False)
        self.assertEqual(fonte.nome, "ERA5Land_AquaCrop_Voronoi")


if __name__ == "__main__":
    unittest.main()

