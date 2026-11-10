import json
import tempfile
import unittest
import pandas as pd
from pathlib import Path
from soilframe.models.modelo_solo import ModeloSolo
from soilframe import (
    ArquivoFonte,
    Dataset,
    EstrategiaTransformacao,
    Metricas,
    RepositorioModelos,
    S3Curado,
    Registry,
)

class UpperStrategy(EstrategiaTransformacao):
    def transformar(self, dados):
        result = dados.copy()
        result["nome"] = result["nome"].str.upper()
        return result


class ArchitectureTests(unittest.TestCase):
    def test_fonte_valida_schema_e_pipeline_ajusta_transforma(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dados.csv"
            frame = pd.DataFrame({"nome": ["a", "b"]})
            frame.to_csv(path, index=False)
            fonte = ArquivoFonte(path, schema={"nome": str})
            self.assertTrue(fonte.validar_schema())

            from soilframe.builtin import PipelinePrecipitacao
            pipeline = PipelinePrecipitacao(fonte=fonte, estrategia=UpperStrategy())
            pipeline.ajustar()
            result = pipeline.transformar()
            self.assertEqual(result.data["nome"].tolist(), ["A", "B"])
            self.assertTrue(result.metadata["fitted"])

    def test_modelo_avalia_e_repositorio_promove(self):
        data = Dataset(pd.DataFrame({"tipo_solo_principal": ["A", "A", "B"]}))
        model = ModeloSolo().treinar(data)
        metrics = model.avaliar(data)
        self.assertIn("accuracy", metrics.valores)
        self.assertTrue(Metricas({"accuracy": 1}).comparar(metrics))
        with tempfile.TemporaryDirectory() as directory:
            repo = RepositorioModelos(directory)
            pipeline = Registry().get_pipeline("pipeline_solo")
            path = repo.registrar(model, pipeline, metrics)
            metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["model"], model.name)
            self.assertEqual(metadata["model_version"], model.version)
            self.assertEqual(metadata["pipeline"], pipeline.name)
            self.assertEqual(metadata["pipeline_version"], pipeline.version)
            repo.promover(model.name, model.version, "Production")
            loaded = repo.obter(model.name)
            self.assertEqual(loaded.name, model.name)
            self.assertTrue((path / "metadata.json").exists())

    def test_repositorio_rejeita_pipeline_ausente(self):
        model = ModeloSolo().treinar(Dataset(pd.DataFrame({"tipo_solo_principal": ["A"]})))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                RepositorioModelos(directory).registrar(model, None, Metricas())

    def test_s3_curado_pode_ser_fonte_local_durante_desenvolvimento(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "curado.csv"
            pd.DataFrame({"valor": [1]}).to_csv(path, index=False)
            source = S3Curado(str(path))
            self.assertEqual(source.extrair().iloc[0]["valor"], 1)

    def test_pipeline_mapa_gera_frames_anuais_e_gif(self):
        from soilframe.builtin import PipelinePrecipitacao

        data = Dataset(
            pd.DataFrame(
                {
                    "ano": [2022, 2022, 2023, 2023],
                    "lat": [-15.0, -16.0, -15.0, -16.0],
                    "lon": [-47.0, -48.0, -47.0, -48.0],
                    "chuva": [10, 20, 30, 40],
                }
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            result = PipelinePrecipitacao().mapa(
                data,
                valor="chuva",
                output_dir=directory,
            )
            self.assertEqual(result.metadata["anos"], [2022, 2023])
            self.assertEqual(len(result.metadata["mapas"]), 2)
            self.assertTrue(Path(result.metadata["gif"]).exists())
            self.assertTrue(all(Path(path).exists() for path in result.metadata["mapas"]))

    def test_pipeline_mapa_valida_colunas_obrigatorias(self):
        from soilframe.builtin import PipelinePrecipitacao

        data = Dataset(pd.DataFrame({"ano": [2024], "lat": [-15], "lon": [-47]}))
        with self.assertRaises(KeyError):
            PipelinePrecipitacao().mapa(data, valor="inexistente", criar_gif=False)

    def test_pipeline_mapa_usa_apenas_coordenadas_do_brasil(self):
        from soilframe.builtin import PipelinePrecipitacao

        data = Dataset(
            pd.DataFrame(
                {
                    "ano": [2024, 2024],
                    "lat": [-15.0, 40.0],
                    "lon": [-47.0, -3.0],
                    "valor": [10, 99],
                }
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            result = PipelinePrecipitacao().mapa(
                data,
                valor="valor",
                output_dir=directory,
                criar_gif=False,
            )
            self.assertEqual(result.metadata["regiao_mapa"], "Brasil")
            self.assertEqual(result.metadata["registros_mapa"], 1)


if __name__ == "__main__":
    unittest.main()
