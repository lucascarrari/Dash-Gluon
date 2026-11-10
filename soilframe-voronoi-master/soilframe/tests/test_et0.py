import io
import tempfile
import unittest
import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
from pathlib import Path
from soil_analysis import et0
from unittest.mock import patch
from shapely.geometry import box


def criar_dataset_et0(
    datas=None,
    valores=None,
    lats=None,
    lons=None,
    nome=et0.VARIAVEL_ET0,
):
    datas = pd.date_range('2024-01-01', '2024-12-31', freq='D') if datas is None else datas
    lats = np.array([-10.0, -9.9]) if lats is None else np.asarray(lats)
    lons = np.array([-50.0, -49.9]) if lons is None else np.asarray(lons)
    if valores is None:
        valores = np.ones((len(datas), len(lats), len(lons)), dtype='float32')
    ds = xr.Dataset(
        {nome: (('time', 'latitude', 'longitude'), valores)},
        coords={'time': datas, 'latitude': lats, 'longitude': lons},
        attrs={'title': 'Fonte sintética BR-DWGD'},
    )
    ds[nome].attrs = {'units': 'mm day-1', 'long_name': 'Reference evapotranspiration'}
    return ds


class FakeZipInfo:
    def __init__(self, file_size):
        self.file_size = file_size

    def is_dir(self):
        return False


class FakeRemoteZip:
    def __init__(self, payload):
        self.payload = payload
        self.opened = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def namelist(self):
        return ['arquivo_ignorado.txt', et0.ET0_ARCHIVE_MEMBER]

    def getinfo(self, member):
        self.opened.append(('getinfo', member))
        return FakeZipInfo(len(self.payload))

    def open(self, member, mode='r'):
        self.opened.append(('open', member, mode))
        return io.BytesIO(self.payload)


class TestCarregarET0Anual(unittest.TestCase):
    def test_aceita_ruido_float32_na_grade_de_decimo_de_grau(self):
        lats = np.arange(-33.85, 5.35 + 0.05, 0.1, dtype='float32')
        lons = np.arange(-73.95, -34.95 + 0.05, 0.1, dtype='float32')
        et0._validar_eixo_espacial(xr.DataArray(lats, dims='latitude'), -90, 90, 'latitude')
        et0._validar_eixo_espacial(xr.DataArray(lons, dims='longitude'), -180, 180, 'longitude')

    def test_carrega_apenas_ano_completo_e_preserva_metadados(self):
        datas = pd.date_range('2023-12-31', '2024-12-31', freq='D')
        ds = criar_dataset_et0(datas=datas)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'et0.nc'
            ds.to_netcdf(path, engine='netcdf4')
            resultado = et0.carregar_et0_anual(path, 2024)

        self.assertEqual(resultado.name, 'ET0')
        self.assertEqual(resultado.sizes['time'], 366)
        self.assertEqual(str(resultado.time.values[0])[:10], '2024-01-01')
        self.assertEqual(str(resultado.time.values[-1])[:10], '2024-12-31')
        self.assertEqual(resultado.attrs['units'], 'mm day-1')
        self.assertEqual(resultado.attrs['dataset_title'], 'Fonte sintética BR-DWGD')
        self.assertEqual(resultado.attrs['dias_no_ano'], 366)

    def test_rejeita_calendario_incompleto(self):
        ds = criar_dataset_et0(datas=pd.date_range('2024-01-02', '2024-12-31', freq='D'))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'incompleto.nc'
            ds.to_netcdf(path, engine='netcdf4')
            with self.assertRaisesRegex(ValueError, 'exatamente as 366 datas'):
                et0.carregar_et0_anual(path, 2024)

    def test_rejeita_nome_da_variavel_oficial_em_cache_derivado(self):
        ds = criar_dataset_et0(nome=et0.VARIAVEL_FONTE_ET0)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'fonte_oficial.nc'
            ds.to_netcdf(path, engine='netcdf4')
            with self.assertRaisesRegex(ValueError, 'Variável ET0 não encontrada'):
                et0.carregar_et0_anual(path, 2024)

    def test_rejeita_variavel_grade_e_valores_invalidos(self):
        casos = []
        casos.append(('variável', criar_dataset_et0(nome='outra'), 'Variável ET0 não encontrada'))
        casos.append(
            (
                'grade',
                criar_dataset_et0(lats=[-10.0, -9.9, -9.7], valores=np.ones((366, 3, 2))),
                'não forma uma grade regular',
            )
        )
        valores_infinitos = np.ones((366, 2, 2), dtype='float32')
        valores_infinitos[10, 0, 0] = np.inf
        casos.append(('infinito', criar_dataset_et0(valores=valores_infinitos), 'valores infinitos'))
        valores_negativos = np.ones((366, 2, 2), dtype='float32')
        valores_negativos[10, 0, 0] = -0.1
        casos.append(('negativo', criar_dataset_et0(valores=valores_negativos), 'valores negativos'))

        with tempfile.TemporaryDirectory() as temp_dir:
            for indice, (rotulo, ds, mensagem) in enumerate(casos):
                with self.subTest(rotulo=rotulo):
                    path = Path(temp_dir) / f'caso_{indice}.nc'
                    ds.to_netcdf(path, engine='netcdf4')
                    with self.assertRaisesRegex(ValueError, mensagem):
                        et0.carregar_et0_anual(path, 2024)


class TestGarantirET0(unittest.TestCase):
    def test_converte_variavel_fonte_cria_cache_atomico_e_reutiliza_offline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            origem = temp_dir / 'origem.nc'
            criar_dataset_et0(nome=et0.VARIAVEL_FONTE_ET0).to_netcdf(origem, engine='netcdf4')
            zip_remoto = FakeRemoteZip(origem.read_bytes())
            cache_dir = temp_dir / 'cache'

            with patch.object(et0, 'ET0_CACHE_DIR', cache_dir), patch.object(
                et0, '_abrir_zip_remoto', return_value=zip_remoto
            ):
                cache = et0.garantir_et0_brdwgd(2024)

            self.assertTrue(cache.is_file())
            self.assertIn(('open', et0.ET0_ARCHIVE_MEMBER, 'r'), zip_remoto.opened)
            self.assertEqual([item.name for item in cache_dir.iterdir()], [cache.name])
            with xr.open_dataset(cache) as ds_cache:
                self.assertEqual(ds_cache.attrs['title'], 'Fonte sintética BR-DWGD')
                self.assertEqual(ds_cache.attrs['source_archive_member'], et0.ET0_ARCHIVE_MEMBER)
                self.assertEqual(ds_cache.attrs['source_variable'], et0.VARIAVEL_FONTE_ET0)
                self.assertEqual(ds_cache.attrs['derived_variable'], et0.VARIAVEL_ET0)
                self.assertEqual(ds_cache.sizes['time'], 366)
                self.assertEqual(list(ds_cache.data_vars), [et0.VARIAVEL_ET0])
                self.assertEqual(ds_cache[et0.VARIAVEL_ET0].dtype, np.dtype('float32'))
                self.assertEqual(ds_cache[et0.VARIAVEL_ET0].attrs['standard_name'], et0.VARIAVEL_ET0)
                self.assertNotIn('valid_min', ds_cache[et0.VARIAVEL_ET0].attrs)
                self.assertNotIn('valid_max', ds_cache[et0.VARIAVEL_ET0].attrs)

            bytes_validos = cache.read_bytes()
            with patch.object(et0, 'ET0_CACHE_DIR', cache_dir), patch.object(
                et0, '_abrir_zip_remoto', side_effect=AssertionError('rede não deveria ser acessada')
            ):
                self.assertEqual(et0.garantir_et0_brdwgd(2024), cache)

            zip_invalido = FakeRemoteZip(b'not a NetCDF')
            with patch.object(et0, 'ET0_CACHE_DIR', cache_dir), patch.object(
                et0, '_abrir_zip_remoto', return_value=zip_invalido
            ):
                with self.assertRaises(Exception):
                    et0.garantir_et0_brdwgd(2024, force=True)
            self.assertEqual(cache.read_bytes(), bytes_validos)
            self.assertEqual([item.name for item in cache_dir.iterdir()], [cache.name])

    def test_reconstroi_cache_corrompido_sem_exigir_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            origem = temp_dir / 'origem.nc'
            criar_dataset_et0(nome=et0.VARIAVEL_FONTE_ET0).to_netcdf(origem, engine='netcdf4')
            cache_dir = temp_dir / 'cache'
            cache_dir.mkdir()
            cache = cache_dir / 'ET0_2024_BR-DWGD_UFES_UTEXAS_v_3.2.4.nc'
            cache.write_bytes(b'cache corrompido')

            with patch.object(et0, 'ET0_CACHE_DIR', cache_dir), patch.object(
                et0, '_abrir_zip_remoto', return_value=FakeRemoteZip(origem.read_bytes())
            ):
                resultado = et0.garantir_et0_brdwgd(2024)

            self.assertEqual(resultado, cache)
            self.assertEqual(et0.carregar_et0_anual(cache, 2024).sizes['time'], 366)


class TestResumirET0PorSolo(unittest.TestCase):
    def test_pondera_por_cosseno_e_exclui_pixels_ambiguos(self):
        datas = pd.date_range('2024-01-01', '2024-12-31', freq='D')
        valores_dia = np.array([[1.0, 2.0], [3.0, 4.0]], dtype='float32')
        valores = np.broadcast_to(valores_dia, (len(datas), 2, 2)).copy()
        et0_diaria = criar_dataset_et0(
            datas=datas,
            valores=valores,
            lats=[0.0, 60.0],
            lons=[0.0, 1.0],
        )[et0.VARIAVEL_ET0]
        solos = gpd.GeoDataFrame(
            {
                'classe': ['A', 'B', 'C'],
                'geometry': [
                    box(-0.4, -1.0, 0.4, 61.0),
                    box(0.6, -1.0, 1.4, 61.0),
                    box(0.9, -1.0, 1.1, 1.0),
                ],
            },
            crs='EPSG:4326',
        )

        resumo = et0.resumir_et0_por_solo(et0_diaria, solos, ['classe']).set_index('classe')

        self.assertEqual(list(resumo.index), ['A', 'B'])
        self.assertAlmostEqual(resumo.loc['A', 'et0_anual_media_mm'], 610.0)
        self.assertAlmostEqual(resumo.loc['B', 'et0_anual_media_mm'], 1464.0)
        self.assertEqual(resumo.loc['A', 'pixels_et0'], 2)
        self.assertEqual(resumo.loc['B', 'pixels_et0'], 1)
        self.assertEqual(resumo.loc['A', 'pixels_grade_et0'], 2)
        self.assertEqual(resumo.loc['B', 'pixels_grade_et0'], 1)
        self.assertTrue((resumo['cobertura_et0_pct'] == 100.0).all())
        self.assertEqual(resumo.loc['A', 'et0_periodo'], '2024')

    def test_nan_estrutural_reduz_cobertura_sem_contaminar_media(self):
        valores = np.ones((366, 2, 2), dtype='float32')
        valores[:, 0, 0] = np.nan
        et0_diaria = criar_dataset_et0(valores=valores)[et0.VARIAVEL_ET0]
        solos = gpd.GeoDataFrame(
            {'classe': ['A'], 'geometry': [box(-51, -11, -49, -9)]},
            crs='EPSG:4326',
        )

        resumo = et0.resumir_et0_por_solo(et0_diaria, solos, 'classe')

        self.assertEqual(resumo.loc[0, 'pixels_grade_et0'], 4)
        self.assertEqual(resumo.loc[0, 'pixels_et0'], 3)
        self.assertAlmostEqual(resumo.loc[0, 'cobertura_et0_pct'], 75.0)
        self.assertAlmostEqual(resumo.loc[0, 'et0_anual_media_mm'], 366.0)

    def test_aceita_categoria_unica_como_string(self):
        et0_diaria = criar_dataset_et0()[et0.VARIAVEL_ET0]
        solos = gpd.GeoDataFrame(
            {'classe': ['A'], 'geometry': [box(-51, -11, -49, -9)]},
            crs='EPSG:4326',
        )
        resumo = et0.resumir_et0_por_solo(et0_diaria, solos, 'classe')
        self.assertEqual(resumo.loc[0, 'pixels_et0'], 4)
        self.assertAlmostEqual(resumo.loc[0, 'et0_anual_media_mm'], 366.0)


if __name__ == '__main__':
    unittest.main()
