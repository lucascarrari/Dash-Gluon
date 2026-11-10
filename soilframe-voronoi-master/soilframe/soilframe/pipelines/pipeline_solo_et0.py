from soilframe import Dataset
from soilframe.builtin import PipelineSoloET0 as BuiltinPipelineSoloET0


class PipelineSoloET0(BuiltinPipelineSoloET0):
    """Combina a base de solos com ET0 tabular ou NetCDF."""

    def rodar(self, parameters=None):
        parameters = parameters or {}
        values = self.validate_parameters(parameters)
        from soilframe.inputs import read_input
        import pandas as pd

        solo = read_input(values["dados_solo"])
        et0 = read_input(values["dados_et0"])
        solo_data = solo.data
        et0_data = et0.data
        if hasattr(et0_data, "to_dataframe"):
            et0_data = et0_data.to_dataframe().reset_index()
        if values.get("chave_relacionamento") and hasattr(solo_data, "merge") and hasattr(et0_data, "columns"):
            data = solo_data.merge(et0_data, on=values["chave_relacionamento"], how="outer")
        elif hasattr(solo_data, "reset_index") and hasattr(et0_data, "reset_index"):
            if len(solo_data) != len(et0_data):
                raise ValueError(
                    "Solo e ET0 têm granularidades diferentes; informe uma "
                    "chave_relacionamento ou agregue o ET0 antes da combinação."
                )
            data = pd.concat([solo_data.reset_index(drop=True), et0_data.reset_index(drop=True)], axis=1)
        else:
            data = {"solo": solo_data, "et0": et0_data}
        return Dataset(data, {"pipeline": self.name, "version": self.version, "sources": [solo.metadata, et0.metadata]})

__all__ = ["PipelineSoloET0"]
