import tempfile
import unittest
import pandas as pd
from pathlib import Path
from soilframe import Dataset, Registry
from soilframe.core.prediction import Prediction
from soilframe.models.modelo_solo import ModeloSolo

class FrameworkTests(unittest.TestCase):
    def test_registry_expoe_pipelines_e_modelos_padronizados(self):
        registry = Registry()
        self.assertTrue(registry.list_pipelines())
        self.assertTrue(registry.list_models())
        self.assertTrue(all(item["name"].startswith("pipeline_") for item in registry.list_pipelines()))
        self.assertTrue(all(item["name"].startswith("modelo_") for item in registry.list_models()))

    def test_pipeline_solo_recebe_dados_por_parametro(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "solos.csv"
            pd.DataFrame({"tipo_solo_principal": ["A", "A"], "valor": [1, 2]}).to_csv(source, index=False)
            result = Registry().get_pipeline("pipeline_solo").rodar({"arquivo_solos": source})
            self.assertEqual(len(result.data), 2)
            self.assertEqual(result.metadata["pipeline"], "pipeline_solo")

    def test_modelo_pode_ser_treinado_e_salvo(self):
        model = ModeloSolo().treinar(Dataset(pd.DataFrame({"tipo_solo_principal": ["A", "A", "B"]})))
        prediction = model.prever(pd.DataFrame({"x": [1, 2]}))
        self.assertEqual(prediction.data["previsao_tipo_solo_principal"].iloc[0], "A")
        with tempfile.TemporaryDirectory() as directory:
            model.salvar(directory)
            self.assertTrue((Path(directory) / "model.pkl").exists())

    def test_modelo_dropar_separa_modelo_combinado(self):
        left = ModeloSolo()
        right = ModeloSolo()
        combinado = left.combinar(right)

        separado_left, separado_right = left.dropar(combinado)

        self.assertIs(separado_left, left)
        self.assertIs(separado_right, right)

    def test_modelo_dropar_rejeita_modelo_simples(self):
        with self.assertRaises(TypeError):
            ModeloSolo().dropar(ModeloSolo())

    def test_pipeline_combina_e_remove_colunas(self):
        left = Registry().get_pipeline("pipeline_solo")
        right = Registry().get_pipeline("pipeline_precipitacao")
        combinado = left.combinar(right, on="id")
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "solo.csv"
            second = Path(directory) / "chuva.csv"
            pd.DataFrame({"id": [1, 2], "solo": ["A", "B"], "descartar": [0, 1]}).to_csv(first, index=False)
            pd.DataFrame({"id": [1, 2], "chuva": [10, 20]}).to_csv(second, index=False)
            result = combinado.dropar("descartar").rodar({"left": {"arquivo_solos": first}, "right": {"arquivo_dados": second}})
            self.assertIn("chuva", result.data.columns)
            self.assertNotIn("descartar", result.data.columns)

    def test_prediction_registra_pipeline_e_modelo(self):
        model = ModeloSolo().treinar(Dataset(pd.DataFrame({"tipo_solo_principal": ["A"]})))
        pipeline = Registry().get_pipeline("pipeline_solo")
        dataset = Dataset(pd.DataFrame({"valor": [1]}))
        prediction = Prediction(pipeline, model)
        result = prediction.rodar(dataset)
        self.assertTrue(result.metadata["prediction"])
        self.assertEqual(result.metadata["pipeline"], "pipeline_solo")

    def test_prediction_rejeita_entrada_nula(self):
        model = ModeloSolo()
        pipeline = Registry().get_pipeline("pipeline_solo")
        prediction = Prediction(pipeline, model)
        with self.assertRaises(ValueError):
            prediction.rodar(None)

    def test_modelo_registra_modelo_e_pipeline_no_tracker(self):
        class Tracker:
            def __init__(self):
                self.registro = None

            def registrar_modelo(self, modelo, pipeline, metricas):
                self.registro = (modelo, pipeline, metricas)

        model = ModeloSolo().treinar(Dataset(pd.DataFrame({"tipo_solo_principal": ["A"]})))
        pipeline = Registry().get_pipeline("pipeline_solo")
        tracker = Tracker()
        model.registrar(tracker, pipeline)

        self.assertIs(tracker.registro[0], model)
        self.assertIs(tracker.registro[1], pipeline)
        self.assertEqual(model.pipeline_treinamento, pipeline)

    def test_modelo_registrar_rejeita_pipeline_ausente(self):
        model = ModeloSolo()
        with self.assertRaises(ValueError):
            model.registrar(object(), None)
