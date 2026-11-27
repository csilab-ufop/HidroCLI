# BSD 2-Clause License

# Copyright (c) 2026, base

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:

# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
""" Provides ORM models for Hidro Database.

Field descriptions follow the ANA HIDRO 1.0 data dictionary (Manual do
Usuário, Apêndice A) and the ANA Hidro WebServices payloads. Units are the
ones used by the data dictionary, for example stage in cm and flow in m3/s.
"""

from sqlalchemy import (
    Column, Float, SmallInteger,
    BigInteger, Integer, String,
    DateTime, UniqueConstraint,
    ForeignKey
)
from sqlalchemy.orm import declarative_base

from datetime import datetime

HidroBase = declarative_base()

# (ANA field map now lives on each Column: info={"ana": ...})


class HidroBaseModel(HidroBase):
    """ Abstract model to hold common attributes to Hidro Models. """

    __abstract__ = True

    RegistroID = Column(Integer, primary_key=True, autoincrement=True)
    """int: unique record identifier."""

    DataIns    = Column(DateTime, default=datetime.now)
    """datetime: date of insertion of the record."""

    DataAlt    = Column(DateTime, info={"ana": "Data_Ultima_Alteracao"})
    """datetime: date of last modification of the record."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @classmethod
    def from_json(cls, json_data: dict):
        """Build an instance from a normalized (attribute-keyed) dict."""
        return cls(**{
            column.key: json_data.get(column.key)
            for column in cls.__table__.columns
            if column.key not in ("RegistroID", "DataIns")
        })


class Basin(HidroBaseModel):
    """ Database model for storing Basins data. """

    __tablename__ = 'Bacia'

    Nome    = Column(String, info={"ana": "Nome_Bacia"})
    """string: name of the hydrographic basin."""

    Codigo  = Column(Integer, unique=True, info={"ana": "codigobacia"})
    """int: unique identifier of hydrographic basin."""



class SubBasin(HidroBaseModel):
    """ Database model for storing Sub Basins data. """

    __tablename__ = 'SubBacia'

    Nome        = Column(String, info={"ana": "Sub_Bacia_Nome"})
    """string: name of the hydrographic sub-basin."""

    Codigo      = Column(Integer, unique=True, info={"ana": "codigosubbacia"})
    """int: unique identifier of hydrographic sub-basin."""

    BaciaCodigo = Column(Integer, ForeignKey("Bacia.Codigo"), info={"ana": "Bacia_Codigo"})
    """int: identifier of which basin the given sub-basin belongs."""



class Entity(HidroBaseModel):
    """ Database model for storing Entity data. """

    __tablename__ = 'Entidade'

    Nome    = Column(String, info={"ana": "Entidade_Nome"})
    """string: name of the entity."""

    Sigla   = Column(String, info={"ana": "Entidade_Sigla"})
    """string: acronym of the entity."""

    Codigo  = Column(Integer, unique=True, info={"ana": "codigoentidade"})
    """int: unique identifier of the entity."""



class Township(HidroBaseModel):
    """ Database model for storing Township data. """

    __tablename__ = 'Municipio'

    Nome       = Column(String, info={"ana": "Municipio_Nome"})
    """string: name of the town. """

    Codigo     = Column(Integer, unique=True, info={"ana": "codigomunicipio"})
    """int: unique identifier of the town on Hidro."""

    CodigoIBGE = Column(Integer, info={"ana": "Municipio_Codigo_IBGE"})
    """int: identifier of the town based on IBGE."""

    EstadoCodigo = Column(Integer, ForeignKey("Estado.Codigo"), info={"ana": "Estado_Codigo"})
    """int: identifier of the state which the town belongs to."""



class River(HidroBaseModel):
    """ Database model for storing Rivers data. """

    __tablename__ = 'Rio'

    Nome              = Column(String, info={"ana": "Nome_Rio"})
    """string: the name of the river. """

    Codigo            = Column(Integer, unique=True, info={"ana": "codigorio"})
    """int: unique identifier of the river. """

    Jurisdicao        = Column(SmallInteger, info={"ana": "Rio_Jurisdicao"})
    """
    int: river jurisdiction.
    1 - Federal
    2 - State
    3 - Undefined
    """

    BaciaCodigo       = Column(Integer, ForeignKey("Bacia.Codigo"), info={"ana": "Bacia_Codigo"})
    """int: identifier of which basin the given river belongs."""

    SubBaciaCodigo    = Column(Integer, ForeignKey("SubBacia.Codigo"), info={"ana": "Sub_Bacia_Codigo"})
    """int: identifier of which sub-basin the given river belongs."""



class State(HidroBaseModel):
    """ Database model for storing States data. """

    __tablename__ = 'Estado'

    Nome       = Column(String, info={"ana": "Estado_Nome"})
    """string: name of the state."""

    Sigla      = Column(String, unique=True, info={"ana": "Estado_Sigla"})
    """string: acronym of the state."""

    Codigo     = Column(Integer, unique=True, info={"ana": "codigouf"})
    """int: unique identifier of the state on Hidro."""

    CodigoIBGE = Column(Integer, info={"ana": "Estado_Codigo_IBGE"})
    """int: identifier of the state on IBGE."""



class Station(HidroBaseModel):
    """ Database model for storing Stations data. """

    __tablename__ = 'Estacao'

    Altitude                      = Column(Float, info={"ana": "Altitude"})
    """float: altitude of the station. """

    AreaDrenagem                  = Column(Float, info={"ana": "Area_Drenagem"})
    """float: drainage area of the station in km2."""

    CodigoAdicional               = Column(String(15), info={"ana": "Codigo_Adicional"})
    """string: original or additional identifier of the station."""

    OperadoraUnidade              = Column(Integer, info={"ana": "Codigo_Operadora_Unidade_UF"})
    """int: code of the operator unity of the station."""

    PeriodoDescLiquidaFim         = Column(SmallInteger, info={"ana": "Data_Periodo_Desc_Liquida_Fim"})
    """datetime: final date of observation of discharge flow on the station."""

    PeriodoDescLiquidaInicio      = Column(SmallInteger, info={"ana": "Data_Periodo_Desc_liquida_Inicio"})
    """ datetime: start date of observation of discharge flow on the station. """

    PeriodoClimatologicaFim       = Column(DateTime, info={"ana": "Data_Periodo_Climatologica_Fim"})
    """datetime: final date of observation of climatology on the station."""

    PeriodoClimatologicaInicio    = Column(DateTime, info={"ana": "Data_Periodo_Climatologica_Inicio"})
    """datetime: start date of observation of climatology on the station."""

    PeriodoEscalaFim              = Column(DateTime, info={"ana": "Data_Periodo_Escala_Fim"})
    """datetime: final date of observation of scale on the station."""

    PeriodoEscalaInicio           = Column(DateTime, info={"ana": "Data_Periodo_Escala_Inicio"})
    """datetime: start date of observation of scale the station."""

    PeriodoPiezometriaFim         = Column(DateTime, info={"ana": "Data_Periodo_Piezometria_Fim"})
    """datetime: final date of observation of piezometry on the station."""

    PeriodoPiezometriaInicio      = Column(DateTime, info={"ana": "Data_Periodo_Piezometria_Inicio"})
    """datetime: start date of observation of piezometry on the station."""

    PeriodoPluviometroFim         = Column(DateTime, info={"ana": "Data_Periodo_Pluviometro_Fim"})
    """datetime: final date of observation of pluviometry on the station."""

    PeriodoPluviometroInicio      = Column(DateTime, info={"ana": "Data_Periodo_Pluviometro_Inicio"})
    """datetime: start date of observation of pluviometry on the station."""

    PeriodoQualAguaFim            = Column(DateTime, info={"ana": "Data_Periodo_Qual_Agua_Fim"})
    """datetime: final date of observation of water quality on the station."""

    PeriodoQualAguaInicio         = Column(DateTime, info={"ana": "Data_Periodo_Qual_Agua_Inicio"})
    """datetime: start date of observation of water quality on the station."""

    PeriodoRegistradorChuvaFim    = Column(DateTime, info={"ana": "Data_Periodo_Registrador_Chuva_Fim"})
    """datetime: final date of observation of rain on the station."""

    PeriodoRegistradorChuvaInicio = Column(DateTime, info={"ana": "Data_Periodo_Registrador_Chuva_Inicio"})
    """datetime: start date of observation of rain on the station."""

    PeriodoRegistradorNivelFim    = Column(DateTime, info={"ana": "Data_Periodo_Registrador_Nivel_Fim"})
    """datetime: final date of observation of level registry on the station."""

    PeriodoRegistradorNivelInicio = Column(DateTime, info={"ana": "Data_Periodo_Registrador_Nivel_Inicio"})
    """datetime: start date of observation of level registry on the station."""

    PeriodoSedimentosFim          = Column(DateTime, info={"ana": "Data_Periodo_Sedimento_Fim"})
    """datetime: final date of observation of sediments on the station."""

    PeriodoSedimentosInicio       = Column(DateTime, info={"ana": "Data_Periodo_Sedimento_Inicio"})
    """datetime: start date of observation of sediments on the station."""

    PeriodoTanqueEvapoFim         = Column(DateTime, info={"ana": "Data_Periodo_Tanque_Evapo_Fim"})
    """datetime: final date of observation of tank evaporation on the station."""

    PeriodoTanqueEvapoInicio      = Column(DateTime, info={"ana": "Data_Periodo_Tanque_Evapo_Inicio"})
    """datetime: start date of observation of tank evaporation on the station."""

    PeriodoTelemetricaFim         = Column(DateTime, info={"ana": "Data_Periodo_Telemetrica_Fim"})
    """datetime: final date of observation of telemetry on the station."""

    PeriodoTelemetricaInicio      = Column(DateTime, info={"ana": "Data_Periodo_Telemetrica_Inicio"})
    """datetime: start date of observation of telemetry on the station."""

    UltimaAtualizacao             = Column(DateTime, info={"ana": "Data_Ultima_Atualizacao"})
    """ datetime: date of last alteration of station data."""

    Nome                          = Column(String(50), info={"ana": "Estacao_Nome"})
    """string: name of the station."""

    Latitude                      = Column(Float, info={"ana": "Latitude"})
    """float: latitude of the station."""

    Longitude                     = Column(Float, info={"ana": "Longitude"})
    """float: longitude of the station."""

    MunicipioCodigo               = Column(Integer, ForeignKey("Municipio.Codigo"), info={"ana": "Municipio_Codigo"})
    """int: identifier of the town which the station is located."""

    EstadoSigla                  = Column(String, ForeignKey("Estado.Sigla"), info={"ana": "UF_Estacao"})
    """ string: acronym of the state where the station is located. """

    OperadoraCodigo               = Column(BigInteger, info={"ana": "Operadora_Codigo"})
    """int: identifier of the operator of the station."""

    OperadoraSubUnidade           = Column(Integer, info={"ana": "Operadora_Sub_Unidade_UF"})
    """int: identifier of the operator sub-unity of the station."""

    Operando                      = Column(SmallInteger, info={"ana": "Operando"})
    """int: identifies if the station still operating. 0 - No. 1 - Yes. """

    ResponsavelCodigo             = Column(BigInteger, info={"ana": "Responsavel_Codigo"})
    """int: identifier of who owns jurisdiction over the station. """

    ResponsavelUnidade            = Column(Integer, info={"ana": "Responsavel_Unidade_UF"})
    """int: identifier of the unity which belongs the station. """

    RioCodigo                     = Column(BigInteger, ForeignKey("Rio.Codigo"), info={"ana": "Rio_Codigo"})
    """int: identifier of the river where is the station."""

    SubBaciaCodigo                = Column(BigInteger, ForeignKey("SubBacia.Codigo"), info={"ana": "Sub_Bacia_Codigo"})
    """int: identifier of the sub-basin where is the station."""

    TipoEstacaoClimatologica      = Column(SmallInteger, info={"ana": "Tipo_Estacao_Climatologica"})
    """int: identifies if the station makes climatological measurements. 0 - No. 1 - Yes. """

    TipoEstacaoDescLiquida        = Column(SmallInteger, info={"ana": "Tipo_Estacao_Desc_Liquida"})
    """int: identifies if the station makes discharge flow measurements. 0 - No. 1 - Yes. """

    TipoEstacao                   = Column(SmallInteger)
    """ int: type of the station. 1 - Fluviometric. 2 - Pluviometric. """

    TipoEstacaoEscala             = Column(SmallInteger, info={"ana": "Tipo_Estacao_Escala"})
    """int: identifies if the station measures stage with scale. 0 - No. 1 - Yes. """

    TipoEstacaoPiezometria        = Column(SmallInteger, info={"ana": "Tipo_Estacao_Piezometria"})
    """int: identifies if the station makes piezometric measurements. 0 - No. 1 - Yes. """

    TipoEstacaoPluviometro        = Column(SmallInteger, info={"ana": "Tipo_Estacao_Pluviometro"})
    """int: identifies if the station makes pluviometric measurements. 0 - No. 1 - Yes. """

    TipoEstacaoQualAgua           = Column(SmallInteger, info={"ana": "Tipo_Estacao_Qual_Agua"})
    """int: identifies if the station makes water quality measurements. 0 - No. 1 - Yes. """

    TipoEstacaoRegistradorChuva   = Column(SmallInteger, info={"ana": "Tipo_Estacao_Registrador_Chuva"})
    """int: identifies if the station measures rainfall with a rain recorder. 0 - No. 1 - Yes. """

    TipoEstacaoRegistradorNivel   = Column(SmallInteger, info={"ana": "Tipo_Estacao_Registrador_Nivel"})
    """int: identifies if the station measures stage with a level recorder. 0 - No. 1 - Yes. """

    TipoEstacaoSedimentos         = Column(SmallInteger, info={"ana": "Tipo_Estacao_Sedimentos"})
    """int: identifies if the station makes sediments measurements. 0 - No. 1 - Yes. """

    TipoEstacaoTanqueEvapo        = Column(SmallInteger, info={"ana": "Tipo_Estacao_Tanque_evapo"})
    """int: identifies if the station makes tank evaporation measurements. 0 - No. 1 - Yes. """

    TipoEstacaoTelemetrica        = Column(SmallInteger, info={"ana": "Tipo_Estacao_Telemetrica"})
    """int: identifies if the station makes telemetric measurements. 0 - No. 1 - Yes. """

    TipoRedeBasica                = Column(SmallInteger, info={"ana": "Tipo_Rede_Basica"})
    """int: identifies if the station is basic type. 0 - No. 1 - Yes. """

    TipoRedeCaptacao              = Column(SmallInteger, info={"ana": "Tipo_Rede_Captacao"})
    """
    int: identifies if the station has captation.
    0 - No.
    1 - Domestic use.
    2 - Industrial use.
    3 - Irrigation use.
    4 - Recreational use.
    5 - Fish farming.
    6 - Generation.
    7 - General.
    """

    TipoRedeClasseVazao           = Column(SmallInteger, info={"ana": "Tipo_Rede_Classe_Vazao"})
    """int:
    0 - No.
    1 - Observated flow rate.
    2 - Natural flow rate.
    3 - Equivalent flow rate.
    4 - Turbinated flow rate.
    5 - Poured flow rate.
    6 - Afluent flow rate.
    7 - Bottom flow rate.
    """

    TipoRedeCursoDagua            = Column(SmallInteger, info={"ana": "Tipo_Rede_Curso_Dagua"})
    """int:
    0 - No.
    1 - Water source.
    2 - Main course.
    3 - Afluent.
    4 - Sub-afluent.
    5 - Other afluent.
    6 - Storm drain.
    7 - Domestic sewer.
    8 - Industrial sewer.
    9 - Other.
    """

    TipoRedeEnergetica            = Column(SmallInteger, info={"ana": "Tipo_Rede_Energetica"})
    """int: identifies if the station is energy-related type. 0 - No. 1 - Yes. """

    TipoRedeEstrategica           = Column(SmallInteger, info={"ana": "Tipo_Rede_Estrategica"})
    """int: identifies if the station is strategical type. 0 - No. 1 - Yes. """

    TipoRedeNavegacao             = Column(SmallInteger, info={"ana": "Tipo_Rede_Navegacao"})
    """int: identifies if the station is navigational type. 0 - No. 1 - Yes. """

    TipoRedeQualAgua              = Column(SmallInteger, info={"ana": "Tipo_Rede_Qual_Agua"})
    """int:
    0 - No.
    1 - Special.
    2 - Freshwater class 1
    3 - Freshwater class 2
    4 - Freshwater class 3
    5 - Freshwater class 4
    6 - Salt water (1)
    7 - Salt water (2)
    8 - Brackish water (1)
    9 - Brackish water (2)
    10 - No classification.
    """

    TipoRedeSedimentos            = Column(SmallInteger, info={"ana": "Tipo_Rede_Sedimentos"})
    """int: identifies if the station is sediment type. 0 - No. 1 - Yes. """

    BaciaCodigo                   = Column(BigInteger, info={"ana": "codigobacia"})
    """int: identifier of the basin where is the station."""

    Codigo                        = Column(BigInteger, unique=True, info={"ana": "codigoestacao"})
    """int: unique identifier of the station."""

class Rain(HidroBaseModel):
    """ Database model for storing Rain data.

    The ANA payload contains daily values; they are stored in the generated
    columns ``Chuva01``..``Chuva31`` and their statuses in
    ``Chuva01Status``..``Chuva31Status``.
    """

    __tablename__  = 'Chuvas'


    __table_args__ = (
        UniqueConstraint('EstacaoCodigo', 'Data', name='uq_rain'),
        {"info": {"station_period": ('PeriodoRegistradorChuvaInicio', 'PeriodoRegistradorChuvaFim')}},
    )

    Data                 = Column(DateTime, info={"ana": "Data_Hora_Dado"})
    """ datetime: date of measurements. """

    DiaMaxima            = Column(SmallInteger, info={"ana": "Dia_Maxima"})
    """ int: day where rained most. """

    Maxima               = Column(Float, info={"ana": "Maxima"})
    """ float: maximum daily rainfall in the month (mm). """

    MaximaStatus         = Column(SmallInteger, info={"ana": "Maxima_Status"})
    """
    int: indicate availability, precision and reliability of maximum value.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Accumulated value.
    """

    NivelConsistencia    = Column(SmallInteger, info={"ana": "Nivel_Consistencia"})
    """
    int: indicates the consistency of the record.
    0 - Raw.
    1 - Consisted.
    """

    NumDiasDeChuva       = Column(SmallInteger, info={"ana": "Numero_Dias_de_Chuva"})
    """ int: number of rainy days in the month. """

    NumDiasDeChuvaStatus = Column(SmallInteger, info={"ana": "Numero_Dias_de_Chuva_Status"})
    """
    int: indicate availability, precision and reliability of rain days.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Accumulated value.
    """

    TipoMedicaoChuvas    = Column(SmallInteger, info={"ana": "Tipo_Medicao_Chuvas"})
    """
    int: indicates the measurement procedure.
    1 - Pluviometry.
    2 - Pluviograph.
    3 - Data logger.
    """

    Total                = Column(Float, info={"ana": "Total"})
    """ float: total rainfall in the month (mm). """

    TotalAnual           = Column(Float, info={"ana": "Total_Anual"})
    """ float: total rainfall in the year (mm). """

    TotalAnualStatus     = Column(SmallInteger, info={"ana": "Total_Anual_Status"})
    """
    int: indicate availability, precision and reliability of total year value of rain.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Accumulated value.
    """

    TotalStatus          = Column(SmallInteger, info={"ana": "Total_Status"})
    """
    int: indicate availability, precision and reliability of month value of rain.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Accumulated value.
    """

    EstacaoCodigo        = Column(BigInteger, ForeignKey("Estacao.Codigo"), info={"ana": "codigoestacao"})
    """int: station code identifier of the record."""

    for i in range(1, 32):
        locals()[f'Chuva{i:02d}'] = Column(f'Chuva{i:02d}', Float, info={"ana": f"Chuva_{i:02d}"})
        locals()[f'Chuva{i:02d}Status'] = Column(f'Chuva{i:02d}Status', SmallInteger, info={"ana": f"Chuva_{i:02d}_Status"})



class DischargeMeasurement(HidroBaseModel):
    """ Database model for storing Discharge Measurements summary data. """

    __tablename__ = 'ResumoDescarga'
    __table_args__ = (
        UniqueConstraint(
            'EstacaoCodigo', 'Data', 'DataAlt', 'NivelConsistencia',
            'Profundidade', 'AreaMolhada', 'Cota', 'Largura',
            'Vazao', 'VelMedia',
            name='uq_discharge_summary_all_cols'
        ),
        {"info": {"station_period": ('PeriodoDescLiquidaInicio', 'PeriodoDescLiquidaFim')}},
    )

    AreaMolhada       = Column(Float, info={"ana": "Area_Molhada (m2)"})
    """ float: wet area of the measurement (m2). """

    Cota              = Column(Float, info={"ana": "Cota (cm)"})
    """ float: stage associated with the discharge measurement (cm). """

    Data              = Column(DateTime, info={"ana": "Data_Hora_Dado"})
    """ datetime: date of the measurement. """

    Largura           = Column(Float, info={"ana": "Largura (m)"})
    """ float: width of the measurement (m). """

    NivelConsistencia = Column(SmallInteger, info={"ana": "Nivel_Consistencia"})
    """
    int: indicates the consistency of the record.
    0 - Raw.
    1 - Consisted.
    """

    Profundidade      = Column(Float, info={"ana": "Profundidade (m)"})
    """ float: depth of the measurement (m). """

    Vazao             = Column(Float, info={"ana": "Vazao (m3/s)"})
    """ float: measured flow rate (m3/s). """

    VelMedia          = Column(Float, info={"ana": "Vel_Media (m/s)"})
    """ float: mean velocity of the measurement (m/s). """

    EstacaoCodigo     = Column(BigInteger, ForeignKey("Estacao.Codigo"), info={"ana": "codigoestacao"})
    """int: station code identifier of the record."""



class Sediments(HidroBaseModel):
    """ Database model for storing Sediments data. """

    __tablename__ = 'Sedimentos'
    __table_args__ = (
        UniqueConstraint('EstacaoCodigo', 'Data', name='uq_sediments'),
        {"info": {"station_period": ('PeriodoSedimentosInicio', 'PeriodoSedimentosFim')}},
    )

    AreaMolhada                = Column(Float, info={"ana": "Area_Molhada"})
    """ float: wet area of the corresponding discharge measurement (m2). """

    ConcentracaoMatSuspensao   = Column(Float, info={"ana": "Concentracao_PPM"})
    """ float: sediment concentration by water volume (mg/l) measured in a determined cross-section of a river. """

    ConcentracaoDaAmostraExtra = Column(Float, info={"ana": "Concentracao_da_Amostra_Extra"})
    """ float: sediment concentration of the extra sample (mg/l) measured in a determined cross-section of a river. """

    CondutividadeEletrica      = Column(Float, info={"ana": "Condutividade_Eletrica"})
    """ float: electrical conductivity (uS/cm at 20 C). """

    Cota                       = Column(Float, info={"ana": "Cota_cm"})
    """ float: associated stage of the corresponding discharge flow measurement (cm). """

    CotaDeMedicao              = Column(Float, info={"ana": "Cota_de_Mediacao"})
    """ float: stage at the sediment sampling cross-section (cm). """

    Data                       = Column(DateTime, info={"ana": "Data_Hora_Dado"})
    """ datetime: date of the sediment measurement. """

    DataLiq                    = Column(DateTime, info={"ana": "Data_Hora_Medicao_Liquida"})
    """ datetime: date of the corresponding liquid discharge measurement. """

    Largura                    = Column(Float, info={"ana": "Largura"})
    """ float: width of the measurement (m). """

    NivelConsistencia          = Column(SmallInteger, info={"ana": "Nivel_Consistencia"})
    """
    int: indicates the consistency of the record.
    0 - Raw.
    1 - Consisted.
    """

    NumMedicao                 = Column(BigInteger, info={"ana": "Numero_Medicao"})
    """ int: sediment measurement number. """

    NumMedicaoLiq              = Column(BigInteger, info={"ana": "Numero_Medicao_Liquida"})
    """ int: number of the corresponding liquid discharge measurement. """

    Observacoes                = Column(String, info={"ana": "Observacoes"})
    """ string: observations about the measurement. """

    TemperaturaDaAgua          = Column(Float, info={"ana": "Temperatura_da_Agua"})
    """
    float: temperature of the water in Celsius measured with manual thermometer
    in contact with water sample in situ.
    """

    Vazao                      = Column(Float, info={"ana": "Vazao_m3_s"})
    """ float: flow of the corresponding liquid discharge measurement (m3/s). """

    Velmedia                   = Column(Float, info={"ana": "Vel_Media"})
    """ float: mean velocity of the corresponding liquid discharge measurement (m/s). """

    EstacaoCodigo              = Column(BigInteger, ForeignKey("Estacao.Codigo"), info={"ana": "codigoestacao"})
    """int: station code identifier of the record."""



class Stage(HidroBaseModel):
    """ Database model for storing Stage data.

    Daily values are stored in the generated columns ``Cota01``..``Cota31``
    and their statuses in ``Cota01Status``..``Cota31Status``.
    """

    __tablename__ = 'Cotas'
    __table_args__ = (
        UniqueConstraint('EstacaoCodigo', 'Data', name='uq_stage'),
        {"info": {"station_period": ('PeriodoRegistradorNivelInicio', 'PeriodoRegistradorNivelFim')}},
    )

    Data              = Column(DateTime, info={"ana": "Data_Hora_Dado"})
    """ datetime: date of measurements. """

    DiaMaxima         = Column(SmallInteger, info={"ana": "Dia_Maxima"})
    """ int: day with maximum measured stage value. """

    DiaMinima         = Column(SmallInteger, info={"ana": "Dia_Minima"})
    """ int: day with minimum measured stage value. """

    Maxima            = Column(Float, info={"ana": "Maxima"})
    """ float: maximum measured stage value in the month. """

    MaximaStatus      = Column(SmallInteger, info={"ana": "Maxima_Status"})
    """ int: indicate availability, precision and reliability of the value.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Dry gauge. """

    Media             = Column(Float, info={"ana": "Media"})
    """ float: average measured stage value in the month. """

    MediaAnual        = Column(Float, info={"ana": "Media_Anual"})
    """ float: average measured stage value in the year. """

    MediaAnualStatus  = Column(SmallInteger, info={"ana": "Media_Anual_Status"})
    """ int: indicate availability, precision and reliability of the value.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Dry gauge. """

    MediaStatus       = Column(SmallInteger, info={"ana": "Media_Status"})
    """ int: indicate availability, precision and reliability of the value.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Dry gauge. """

    MediaDiaria       = Column(SmallInteger, info={"ana": "Mediadiaria"})
    """ int: indicates whether the measurement is a daily average.
    0 - No (instantaneous).
    1 - Yes (daily average). """

    Minima            = Column(Float, info={"ana": "Minima"})
    """ float: minimum measured stage value in the month. """

    MinimaStatus      = Column(SmallInteger, info={"ana": "Minima_Status"})
    """ int: indicate availability, precision and reliability of the value.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Dry gauge. """

    TipoMedicaoCotas  = Column(SmallInteger, info={"ana": "Tipo_Medicao_Cotas"})
    """
    int: indicates measurement procedure.
    1 - Scale.
    2 - Linigraph.
    3 - Data logger.
    """

    EstacaoCodigo     = Column(BigInteger, ForeignKey("Estacao.Codigo"), info={"ana": "codigoestacao"})
    """int: station code identifier of the record."""

    NivelConsistencia = Column(SmallInteger, info={"ana": "nivelconsistencia"})
    """
    int: indicates the consistency of the record.
    0 - Raw.
    1 - Consisted.
    """

    for i in range(1, 32):
        locals()[f'Cota{i:02d}'] = Column(f'Cota{i:02d}', Float, info={"ana": f"Cota_{i:02d}"})
        locals()[f'Cota{i:02d}Status'] = Column(f'Cota{i:02d}Status', SmallInteger, info={"ana": f"Cota_{i:02d}_Status"})



class RatingCurve(HidroBaseModel):
    """ Database model for storing Rating Curve data. """

    __tablename__ = 'CurvaDescarga'
    __table_args__ = (
        UniqueConstraint(
            'EstacaoCodigo',
            'NumeroCurva',
            'PeriodoValidadeInicio',
            'PeriodoValidadeFim',
            name='uq_discharge_flow'
        ),
        {"info": {"station_period": ('PeriodoDescLiquidaInicio', 'PeriodoDescLiquidaFim')}},
    )

    CoefA                 = Column(Float, info={"ana": "Coef_a"})
    """ float: coefficient of the exponential equation. """

    CoefH0                = Column(Float, info={"ana": "Coef_h0"})
    """ float: coefficient of the exponential equation. """

    CoefN                 = Column(Float, info={"ana": "Coef_n"})
    """ float: coefficient of the exponential equation. """

    CoefA0                = Column(Float, info={"ana": "Coefa_0"})
    """ float: coefficient of the polynomial equation (linear, parabolic or cubic). """

    CoefA1                = Column(Float, info={"ana": "Coefa_1"})
    """ float: coefficient of the polynomial equation (linear, parabolic or cubic). """

    CoefA2                = Column(Float, info={"ana": "Coefa_2"})
    """ float: coefficient of the polynomial equation (linear, parabolic or cubic). """

    CoefA3                = Column(Float, info={"ana": "Coefa_3"})
    """ float: coefficient of the polynomial equation (linear, parabolic or cubic). """

    CotaMaxima            = Column(Float, info={"ana": "Cota_Maxima"})
    """ float: maximum stage valid for the rating curve (cm). """

    CotaMinima            = Column(Float, info={"ana": "Cota_Minima"})
    """ float: minimum stage valid for the rating curve (cm). """

    NivelConsistencia     = Column(SmallInteger, info={"ana": "Nivel_Consistencia"})
    """
    int: indicates the consistency of the record.
    0 - Raw.
    1 - Consisted.
    """

    NumeroCurva           = Column(String(5), info={"ana": "Numero_Curva"})
    """string: number that identifies the rating curve, e.g. 1/2, 2/2, 3/4."""

    PeriodoValidadeFim    = Column(DateTime, info={"ana": "Periodo_Validade_Fim"})
    """ datetime: final date of validity of the rating curve. """

    PeriodoValidadeInicio = Column(DateTime, info={"ana": "Periodo_Validade_Inicio"})
    """ datetime: initial date of validity of the rating curve. """

    TabelaPassoCota       = Column(Float, info={"ana": "Tabela_Passo_Cota"})
    """
    float: amount to be added incrementally to the minimum stage to obtain
    the stages from the rating curve table (cm).
    """

    TipoCurva             = Column(SmallInteger, info={"ana": "Tipo_Curva"})
    """
    int: indicates whether the curve should be represented by an equation or
    by a discharge table.
    1 - Equation.
    2 - Table.
    """

    TipoEquacao           = Column(SmallInteger, info={"ana": "Tipo_Equacao"})
    """
    int: Indicates the type of equation that represents the curve (in the case that the
    curve is represented by an equation).
    1 - Power.
    2 - Linear.
    3 - Parabolic.
    4 - Cubic.
    """

    EstacaoCodigo         = Column(BigInteger, ForeignKey("Estacao.Codigo"), info={"ana": "codigoestacao"})
    """int: station code identifier of the record."""



class WaterQuality(HidroBaseModel):
    """ Database model for storing Water Quality data.

    Parameter columns follow the ANA water-quality parameter codes; the
    corresponding per-parameter statuses are stored in
    ``WaterQualityStatus``.
    """

    __tablename__ = 'QualAgua'
    __table_args__ = (
        UniqueConstraint(
            'EstacaoCodigo',
            'Data',
            name='uq_qual_agua'
        ),
        {"info": {"station_period": ('PeriodoQualAguaInicio', 'PeriodoQualAguaFim')}},
    )

    n245T                       = Column(Float, info={"ana": "100_2_4_5_t_mgl"})
    """ float: measured concentration of 2,4,5-T (mg/l). """

    n245TP                      = Column(Float, info={"ana": "101_2_4_5_tp_mgl"})
    """ float: measured concentration of 2,4,5-TP (mg/l). """

    n246Triclorofenol           = Column(Float, info={"ana": "102_2_4_6_Triclorofenol_mgl"})
    """ float: measured concentration of 2,4,6-trichlorophenol (mg/l). """

    Acido24Diclorofenoxiacetico = Column(Float, info={"ana": "103_Acido_2_4_Diclorofenoxiacetico_mgl"})
    """ float: measured concentration of 2,4-dichlorophenoxyacetic acid (mg/l). """

    Aldrin                      = Column(Float, info={"ana": "104_Aldrin_mgl"})
    """ float: measured concentration of aldrin (mg/l). """

    AzinfosEtil                 = Column(Float, info={"ana": "105_Azinfosetil_mgl"})
    """ float: measured concentration of azinphos-ethyl (mg/l). """

    Benzeno                     = Column(Float, info={"ana": "106_Benzeno_mgl"})
    """ float: measured concentration of benzene (mg/l). """

    BenzoAPireno                = Column(Float, info={"ana": "107_Benzoapireno_mgl"})
    """ float: measured concentration of benzo[a]pyrene (mg/l). """

    BHC                         = Column(Float, info={"ana": "108_BHC_mgl"})
    """ float: measured concentration of BHC (mg/l). """

    BifenilasPolicloradas       = Column(Float, info={"ana": "109_Bifenilaspolicloradas_mgl"})
    """ float: measured concentration of polychlorinated biphenyls (PCBs) (mg/l). """

    Escherichia                 = Column(Float, info={"ana": "10_Escherichiacoli_ufc_100ml"})
    """ float: measured count of Escherichia coli (UFC/100 ml). """

    Carbaril                    = Column(Float, info={"ana": "110_Carbaril_mgl"})
    """ float: measured concentration of carbaryl (mg/l). """

    Clordano                    = Column(Float, info={"ana": "111_Clordano_mgl"})
    """ float: measured concentration of chlordane (mg/l). """

    DDEPP                       = Column(Float, info={"ana": "112_DDEPP_mgl"})
    """ float: measured concentration of DDE/DDD (DDEPP) (mg/l). """

    DDT                         = Column(Float, info={"ana": "113_DDT_mgl"})
    """ float: measured concentration of DDT (mg/l). """

    Demeton                     = Column(Float, info={"ana": "114_Demeton_mgl"})
    """ float: measured concentration of demeton (mg/l). """

    Diazinon                    = Column(Float, info={"ana": "115_Diazinon_mgl"})
    """ float: measured concentration of diazinon (mg/l). """

    Dieldrin                    = Column(Float, info={"ana": "116_Dieldrin_mgl"})
    """ float: measured concentration of dieldrin (mg/l). """

    DodecacloroNonacloro        = Column(Float, info={"ana": "117_Dodecaclorononacloro_mgl"})
    """ float: measured concentration of dodecachlor + nonachlor (mg/l). """

    DySystonDisulfton           = Column(Float, info={"ana": "118_Dysystondisulfton_mgl"})
    """ float: measured concentration of disulfoton (mg/l). """

    Endossulfan                 = Column(Float, info={"ana": "119_Endossulfan_mgl"})
    """ float: measured concentration of endosulfan (mg/l). """

    FitoplanctonQuantitativo    = Column(Float, info={"ana": "11_Fitoplancton_Quantitativo_celulas_100ml"})
    """ float: quantitative phytoplankton count (cells/100 ml). """

    Endrin                      = Column(Float, info={"ana": "120_Endrin_mgl"})
    """ float: measured concentration of endrin (mg/l). """

    EpoxidoHeptacloro           = Column(Float, info={"ana": "121_Epoxidoheptacloro_mgl"})
    """ float: measured concentration of heptachlor epoxide (mg/l). """

    Ethion                      = Column(Float, info={"ana": "122_Ethion_mgl"})
    """ float: measured concentration of ethion (mg/l). """

    Gution                      = Column(Float, info={"ana": "123_Gution_mgl"})
    """ float: measured concentration of guthion (mg/l). """

    Heptacloro                  = Column(Float, info={"ana": "124_Heptacloro_mgl"})
    """ float: measured concentration of heptachlor (mg/l). """

    Lindano                     = Column(Float, info={"ana": "125_Lindano_mgl"})
    """ float: measured concentration of lindane (mg/l). """

    Malation                    = Column(Float, info={"ana": "126_Malation_mgl"})
    """ float: measured concentration of malathion (mg/l). """

    MetilParation               = Column(Float, info={"ana": "127_Metilparation_mgl"})
    """ float: measured concentration of methyl parathion (mg/l). """

    Metoxicloro                 = Column(Float, info={"ana": "128_Metoxicloro_mgl"})
    """ float: measured concentration of methoxychlor (mg/l). """

    Paration                    = Column(Float, info={"ana": "129_Paration_mgl"})
    """ float: measured concentration of parathion (mg/l). """

    FosforoTotal                = Column(Float, info={"ana": "12_Fosforo_Total_mgl)"})
    """ float: measured concentration of total phosphorus (mg/l P). """

    Pentaclorofenol             = Column(Float, info={"ana": "130_Pentaclorofenol_mgl"})
    """ float: measured concentration of pentachlorophenol (mg/l). """

    Phosdrin                    = Column(Float, info={"ana": "131_Phosdrin_mgl"})
    """ float: measured concentration of mevinphos (phosdrin) (mg/l). """

    TetracloretoCarbono         = Column(Float, info={"ana": "132_Tetra_Cloreto_Carbono_mgl"})
    """ float: measured concentration of carbon tetrachloride (mg/l). """

    Tetracloroeteno             = Column(Float, info={"ana": "133_Tetra_Cloro_Eteno_mgl"})
    """ float: measured concentration of tetrachloroethene (mg/l). """

    Toxafeno                    = Column(Float, info={"ana": "134_Toxafeno_mgl"})
    """ float: measured concentration of toxaphene (mg/l). """

    Tricloroeteno               = Column(Float, info={"ana": "135_Tricloro_Eteno_mgl"})
    """ float: measured concentration of trichloroethene (mg/l). """

    Algas                       = Column(Float, info={"ana": "136_Algas_n_upa_ml"})
    """ float: measured algae count (UPA/ml). """

    Amoniaco                    = Column(Float, info={"ana": "137_Amoniaco_mgl"})
    """ float: measured concentration of ammonia (mg/l N). """

    BacteriasHeterotroficas     = Column(Float, info={"ana": "138_Bacterias_Heterotroficas_ufc_ml"})
    """ float: measured count of heterotrophic bacteria (UFC/ml). """

    CloroResidual               = Column(Float, info={"ana": "139_Cloro_Residual_mgl"})
    """ float: measured concentration of residual chlorine (mg/l Cl). """

    Nitratos                    = Column(Float, info={"ana": "13_Nitratos_mgl_n)"})
    """ float: measured concentration of nitrates (mg/l N). """

    Colifagos                   = Column(Float, info={"ana": "140_Colifagos_nmp_100ml"})
    """ float: measured count of coliphages (NMP/100 ml). """

    ContagemBacteriasPlaca      = Column(Float, info={"ana": "141_Contagem_Bacterias_Placa_ufc_ml"})
    """ float: plate bacteria count (UFC/ml). """

    EnteroBacteriasPatogenicas  = Column(Float, info={"ana": "142_Entero_Bacterias_Patogenicas_n_org_ml"})
    """ float: measured count of pathogenic enterobacteria (org/ml). """

    Fungos                      = Column(Float, info={"ana": "143_Fungos_ufc_ml"})
    """ float: measured fungi count (UFC/ml). """

    NitrogenioAlbuminoide       = Column(Float, info={"ana": "144_Nitrogenio_Albuminoide_mgl"})
    """ float: measured concentration of albuminoid nitrogen (mg/l). """

    Protozoarios                = Column(Float, info={"ana": "145_Protozoarios_n_org_ml"})
    """ float: measured protozoa count (org/ml). """

    Salmonelas                  = Column(Float, info={"ana": "146_Salmonelas_nmp_ml"})
    """ float: measured count of salmonella (NMP/ml). """

    ZooplanctonTotal            = Column(Float, info={"ana": "147_Zooplanctontotal_n_org_ml"})
    """ float: total zooplankton count (org/ml). """

    NitrogenioAmoniacal         = Column(Float, info={"ana": "14_Nitrogenio_Amoniacal_mgl"})
    """ float: measured concentration of ammoniacal nitrogen (mg/l N). """

    NitrogenioTotal             = Column(Float, info={"ana": "15_Nitrogenio_Total_mgl_n"})
    """ float: measured concentration of total nitrogen (mg/l N). """

    OrtofosfatoTotal            = Column(Float, info={"ana": "16_Ortofosfato_Total_mgl_po4"})
    """ float: measured concentration of total orthophosphate (mg/l PO4). """

    OD                          = Column(Float, info={"ana": "17_OD_mgl_02"})
    """ float: measured concentration of dissolved oxygen (mg/l O2). """

    pH                          = Column(Float, info={"ana": "18_PH"})
    """ float: measured pH. """

    SolDissolvidosTotais        = Column(Float, info={"ana": "19_Soldissolvidos_Totais_mgl"})
    """ float: measured concentration of total dissolved solids (mg/l). """

    AlcalinidadeTotal           = Column(Float, info={"ana": "1_Alcalinidade_Total_mgl_caco3"})
    """ float: measured total alkalinity (mg/l CaCO3). """

    SolSuspensaoTotais          = Column(Float, info={"ana": "20_Solsuspensao_Totais_mgl"})
    """ float: measured concentration of total suspended solids (mg/l). """

    TempAmostra                 = Column(Float, info={"ana": "21_Temperatura_Amostra_c"})
    """ float: measured sample temperature (C). """

    TempAr                      = Column(Float, info={"ana": "22_Tempar_c"})
    """ float: measured air temperature (C). """

    Transparencia               = Column(Float, info={"ana": "23_Transparencia_m"})
    """ float: measured water transparency (m). """

    Turbidez                    = Column(Float, info={"ana": "24_Turbidez_ntu"})
    """ float: measured water turbidity (FTU). """

    Acidez                      = Column(Float, info={"ana": "25_Acidez_mgl_caco3"})
    """ float: measured water acidity (mg/l CaCO3). """

    AlcalinidadeCO3             = Column(Float, info={"ana": "26_Alcalinidade_CO3_mgl"})
    """ float: measured carbonate alkalinity (mg/l). """

    AlcalinidadeHCO3            = Column(Float, info={"ana": "27_Alcalinidade_HCO3_mgl"})
    """ float: measured bicarbonate alkalinity (mg/l). """

    AlcalinidadeOH              = Column(Float, info={"ana": "28_Alcalinidade_OH_mgl"})
    """ float: measured hydroxide alkalinity (mg/l). """

    Aluminiodissolvido          = Column(Float, info={"ana": "29_Aluminio_Dissolvido_mgl"})
    """ float: measured concentration of dissolved aluminium (mg/l). """

    CarbonoOrganicoTotal        = Column(Float, info={"ana": "2_Carbono_Organico_Total_mgl"})
    """ float: measured concentration of total organic carbon (mg/l C). """

    Aluminio                    = Column(Float, info={"ana": "30_Aluminio_mgl_al"})
    """ float: measured concentration of aluminium (mg/l Al). """

    AmoniaNaoIonizavel          = Column(Float, info={"ana": "31_Amonia_Nao_Ionizavel_mgl_nh3"})
    """ float: measured concentration of un-ionized ammonia (mg/l N). """

    Arsenio                     = Column(Float, info={"ana": "32_Arsenio_mgl"})
    """ float: measured concentration of arsenic (mg/l As). """

    Bario                       = Column(Float, info={"ana": "33_Bario_mgl_ba"})
    """ float: measured concentration of barium (mg/l Ba). """

    Berilio                     = Column(Float, info={"ana": "34_Berilio_mgl"})
    """ float: measured concentration of beryllium (mg/l Be). """

    BismutoTotal                = Column(Float, info={"ana": "35_Bismuto_Total_mgl"})
    """ float: measured concentration of total bismuth (mg/l Bi). """

    Borodissolvido              = Column(Float, info={"ana": "36_Borodissolvido_mgl"})
    """ float: measured concentration of dissolved boron (mg/l). """

    Boro                        = Column(Float, info={"ana": "37_Boro_mgl_b"})
    """ float: measured concentration of boron (mg/l B). """

    Cadmio                      = Column(Float, info={"ana": "38_Cadmio_mgl_cd"})
    """ float: measured concentration of cadmium (mg/l Cd). """

    CalcioTotal                 = Column(Float, info={"ana": "39_Calcio_Total_mgl"})
    """ float: measured concentration of total calcium (mg/l Ca). """

    Cloretos                    = Column(Float, info={"ana": "3_Cloretos_mgl_cl"})
    """ float: measured concentration of chlorides (mg/l Cl). """

    Chumbo                      = Column(Float, info={"ana": "40_Chumbo_mgl"})
    """ float: measured concentration of lead (mg/l Pb). """

    Cianetolivre                = Column(Float, info={"ana": "41_Cianeto_Livre_mgl"})
    """ float: measured concentration of free cyanide (mg/l). """

    Cianetos                    = Column(Float, info={"ana": "42_Cianetos_mgl_cn"})
    """ float: measured concentration of cyanides (mg/l CN). """

    Cobalto                     = Column(Float, info={"ana": "43_Cobalto_mgl_co"})
    """ float: measured concentration of cobalt (mg/l Co). """

    Cobredissolvido             = Column(Float, info={"ana": "44_Cobre_Dissolvido_mgl"})
    """ float: measured concentration of dissolved copper (mg/l). """

    Cobre                       = Column(Float, info={"ana": "45_Cobre_mgl_cu"})
    """ float: measured concentration of copper (mg/l Cu). """

    ColiformesFecais            = Column(Float, info={"ana": "46_Coliformes_Fecais_nmp_100ml"})
    """ float: measured count of fecal coliforms (NMP/100 ml). """

    ColiformesTotais            = Column(Float, info={"ana": "47_Coliformes_Totais_nmp_100ml"})
    """ float: measured count of total coliforms (NMP/100 ml). """

    CompostosOrganoclorados     = Column(Float, info={"ana": "48_Compostos_Organo_Clorados_mgl"})
    """ float: measured concentration of organochlorine compounds (mg/l). """

    CompostosOrganofosforados   = Column(Float, info={"ana": "49_Compostos_Organo_Fosforados_mgl"})
    """ float: measured concentration of organophosphorus compounds (mg/l). """

    CondutividadeEletrica       = Column(Float, info={"ana": "50_Condutivida_de_Eletrica_us_cm_a_20c"})
    """ float: measured electrical conductivity (uS/cm at 20 C). """

    Cor                         = Column(Float, info={"ana": "51_COR_mg_pt_col"})
    """ float: measured colour (mg Pt/Co). """

    CromoHexavalente            = Column(Float, info={"ana": "52_Cromo_Hexavalente_mgl"})
    """ float: measured concentration of hexavalent chromium (mg/l Cr). """

    CromoTotal                  = Column(Float, info={"ana": "53_Cromo_Total_mgl_cr"})
    """ float: measured concentration of total chromium (mg/l Cr). """

    CromoTrivalente             = Column(Float, info={"ana": "54_Cromo_Trivalente_mgl"})
    """ float: measured concentration of trivalent chromium (mg/l Cr). """

    Densidadecianobacterias     = Column(Float, info={"ana": "55_Densidade_Ciano_Bacterias_cel_ml"})
    """ float: measured cyanobacteria density (cells/ml). """

    Detergentes                 = Column(Float, info={"ana": "56_Detergentes_mgl_las"})
    """ float: measured concentration of detergents (mg/l LAS). """

    Dureza                      = Column(Float, info={"ana": "57_Dureza_mgl_caco3"})
    """ float: measured hardness (mg/l). """

    Durezamagnesio              = Column(Float, info={"ana": "58_Dureza_Magnesio_mgl_mgco3"})
    """ float: measured magnesium hardness (mg/l MgCO3). """

    DurezaTotal                 = Column(Float, info={"ana": "59_Dureza_Total_mgl"})
    """ float: measured total hardness (mg/l CaCO3). """

    ColiformesTermotolerantes   = Column(Float, info={"ana": "5_Coliformes_Termo_Tolerantes_ufc_100ml"})
    """ float: measured count of thermotolerant coliforms (UFC/100 ml). """

    EstreptococosFecais         = Column(Float, info={"ana": "61_Estreptococos_Fecais_nmp_100ml"})
    """ float: measured count of fecal streptococci (NMP/100 ml). """

    FerroDissolvido             = Column(Float, info={"ana": "62_Ferro_Dissolvido_mgl"})
    """ float: measured concentration of dissolved iron (mg/l). """

    FerroTotal                  = Column(Float, info={"ana": "63_Ferro_Total_mgl"})
    """ float: measured concentration of total iron (mg/l Fe). """

    Fluoretos                   = Column(Float, info={"ana": "64_Fluoretos_mgl"})
    """ float: measured concentration of fluorides (mg/l F). """

    FosfatoTotal                = Column(Float, info={"ana": "65_Fosfato_Total_mgl"})
    """ float: measured concentration of total phosphate (mg/l P). """

    Hidrocarbonetos             = Column(Float, info={"ana": "66_Hidrocarbonetos_mgl"})
    """ float: measured concentration of hydrocarbons (mg/l). """

    IndiceFenois                = Column(Float, info={"ana": "67_Indicefenois_mgl_c6h5oh"})
    """ float: measured phenol index (mg/l C6H5OH). """

    IQA                         = Column(Float, info={"ana": "68_IQA"})
    """ float: water quality index (IQA). """

    Litio                       = Column(Float, info={"ana": "69_Litio_mgl"})
    """ float: measured concentration of lithium (mg/l Li). """

    CondutividadeEspecifica     = Column(Float, info={"ana": "6_Condutividade_Especifica_25oc_us_cm_a_25c"})
    """ float: measured specific conductivity (uS/cm at 25 C). """

    MagnesioTotal               = Column(Float, info={"ana": "70_Magnesio_Total_mgl"})
    """ float: measured concentration of total magnesium (mg/l Mg). """

    Manganes                    = Column(Float, info={"ana": "71_Manganes_mgl"})
    """ float: measured concentration of manganese (mg/l Mn). """

    Mercurio                    = Column(Float, info={"ana": "72_Mercurio_mgl"})
    """ float: measured concentration of mercury (mg/l Hg). """

    Niquel                      = Column(Float, info={"ana": "73_Niquel_mgl"})
    """ float: measured concentration of nickel (mg/l Ni). """

    Nitritos                    = Column(Float, info={"ana": "74_Nitritos_mgl"})
    """ float: measured concentration of nitrites (mg/l N). """

    NitrogenioOrganico          = Column(Float, info={"ana": "75_Nitrogenio_Organico_mgl"})
    """ float: measured concentration of organic nitrogen (mg/l). """

    NitrogenioTotalKJELDAHL     = Column(Float, info={"ana": "76_Nitrogenio_Total_kjeldahl_mgl"})
    """ float: measured concentration of total Kjeldahl nitrogen (mg/l N). """

    OleosGraxas                 = Column(Float, info={"ana": "77_Oleos_graxas_mgl"})
    """ float: measured concentration of oils and greases (mg/l). """

    ODsaturacao                 = Column(Float, info={"ana": "78_OD_perc_saturacao"})
    """ float: measured dissolved oxygen saturation (%). """

    PotassioTotal               = Column(Float, info={"ana": "79_Potassio_Total_mgl"})
    """ float: measured concentration of total potassium (mg/l K). """

    DBO                         = Column(Float, info={"ana": "7_DBO_mgl_02)"})
    """ float: measured biochemical oxygen demand (mg/l O2). """

    Prata                       = Column(Float, info={"ana": "80_Prata_mgl"})
    """ float: measured concentration of silver (mg/l Ag). """

    ParametroProfundidade       = Column(Float, info={"ana": "81_Parametro_Profundidade_m"})
    """ float: depth at which the water-quality parameter was measured (m). """

    Selenio                     = Column(Float, info={"ana": "82_Selenio_mgl"})
    """ float: measured concentration of selenium (mg/l Se). """

    SilicaDissolvida            = Column(Float, info={"ana": "83_Silicadissolvida_mgl"})
    """ float: measured concentration of dissolved silica (mg/l SiO2). """

    SodioTotal                  = Column(Float, info={"ana": "84_Sodiototal_mgl"})
    """ float: measured concentration of total sodium (mg/l Na). """

    SolDissolvidosFixos         = Column(Float, info={"ana": "85_Soldissolvidos_Fixos_mgl_a_180c)"})
    """ float: measured concentration of fixed dissolved solids (mg/l at 180 C). """

    SolDissolvidosVolateis      = Column(Float, info={"ana": "86_Soldissolvidos_Volateis_mgl"})
    """ float: measured concentration of volatile dissolved solids (mg/l). """

    SolSuspensaoFixos           = Column(Float, info={"ana": "87_Sol_Suspensao_Fixos_mgl"})
    """ float: measured concentration of fixed suspended solids (mg/l). """

    SolSuspensaoVolateis        = Column(Float, info={"ana": "88_Sol_Suspensao_Volateis_mgl"})
    """ float: measured concentration of volatile suspended solids (mg/l). """

    SolFixos                    = Column(Float, info={"ana": "89_Solfixos_mgl"})
    """ float: measured concentration of fixed solids (mg/l). """

    DescargaLiquida             = Column(Float, info={"ana": "8_Descarga_Liquida_m3s"})
    """ float: measured liquid discharge (m3/s). """

    SolSedimentaveis            = Column(Float, info={"ana": "90_Sol_sedimentaveis_mgl"})
    """ float: measured concentration of settleable solids (mg/l). """

    SolTotais                   = Column(Float, info={"ana": "91_Sol_totais_mgl"})
    """ float: measured concentration of total solids (mg/l). """

    SolVolateis                 = Column(Float, info={"ana": "92_Sol_Volateis_mgl"})
    """ float: measured concentration of volatile solids (mg/l). """

    Sulfatos                    = Column(Float, info={"ana": "93_Sulfatos_mgl"})
    """ float: measured concentration of sulfates (mg/l SO4). """

    Sulfetos                    = Column(Float, info={"ana": "94_Sulfetos_mgl"})
    """ float: measured concentration of sulfides (mg/l S). """

    UranioTotal                 = Column(Float, info={"ana": "95_Uranio_Total_mgl"})
    """ float: measured concentration of total uranium (mg/l U). """

    Vanadio                     = Column(Float, info={"ana": "96_Vanadio_mgl"})
    """ float: measured concentration of vanadium (mg/l V). """

    Zinco                       = Column(Float, info={"ana": "97_Zinco_mgl"})
    """ float: measured concentration of zinc (mg/l Zn). """

    n11Dicloroeteno             = Column(Float, info={"ana": "98_1_1_Dicloroeteno_mgl"})
    """ float: measured concentration of 1,1-dichloroethene (mg/l). """

    n12Dicloroetano             = Column(Float, info={"ana": "99_1_2_Dicloroetano_mgl"})
    """ float: measured concentration of 1,2-dichloroethane (mg/l). """

    DQO                         = Column(Float, info={"ana": "9_DQO_mgl_02)"})
    """ float: measured chemical oxygen demand (mg/l O2). """

    Choveu                      = Column(SmallInteger, info={"ana": "Choveu"})
    """ int: indicates whether it rained during the measurement.
    0 - No.
    1 - Yes. """

    Data                        = Column(DateTime, info={"ana": "Data_Hora_Dado"})
    """ datetime: date of measurements. """

    NivelConsistencia           = Column(SmallInteger, info={"ana": "Nilvel_ConsistÃªncia"})
    """
    int: indicates the consistency of the record.
    0 - Raw.
    1 - Consisted.
    """

    NumMedicao                  = Column(BigInteger, info={"ana": "Num_Medicao"})
    """ int: water-quality measurement number (1-9999). """

    PosHorizColeta              = Column(SmallInteger, info={"ana": "Posicao_Horizontal_Coleta"})
    """ int: horizontal sampling position.
    1 - Right bank.
    2 - Centre.
    3 - Left bank.
    4 - Composite.
    5 - Extra.
    6 - Undefined.
    7 - Surface.
    8 - Integrated.
    9 - 40%.
    10 - 50%. """

    PosVertColeta               = Column(SmallInteger, info={"ana": "Posicao_Vertical_Coleta"})
    """ int: vertical sampling position.
    1 - Undefined.
    2 - Surface.
    3 - Integrated.
    4 - Bottom.
    5 - 20%.
    6 - 40%.
    7 - 50%.
    8 - 60%.
    9 - 70%.
    10 - 80%. """

    Profundidade                = Column(Float, info={"ana": "Profundidade_m"})
    """ float: measurement depth (m). """

    EstacaoCodigo               = Column(BigInteger, ForeignKey("Estacao.Codigo"), info={"ana": "codigoestacao"})
    """int: station code identifier of the record."""



class WaterQualityStatus(HidroBaseModel):
    """ Database model for storing Water Quality Status data.

    One status column is generated for each ANA water-quality parameter:
    ``QualAgua001Status``..``QualAgua147Status``.
    """

    __tablename__ = 'QualAguaStatus'

    QualAguaID = Column(Integer, ForeignKey("QualAgua.RegistroID"), nullable=False, info={"ana": "QualAguaID"})
    """ int: foreign key to the water-quality measurement. """
    
    locals().update({
        f'QualAgua{i:03d}Status': Column(f'QualAgua{i:03d}Status', SmallInteger, info={"ana": f"{i}_Status"})
        for i in range(1, 148)
    })



class Granulometry(HidroBaseModel):
    """ Database model for storing Granulometry data.

    The sample is split into bed material (``MatFundo*``), bed load
    (``MatArraste*``) and suspended sediment (``MatSusp*``) fractions. Size
    columns give cumulative percentages finer than a grain size; ``*D10`` to
    ``*D90`` give the grain diameter at which the corresponding percentage
    of the sample is finer.
    """

    __tablename__ = 'Granulometria'
    __table_args__ = (
        UniqueConstraint(
            'EstacaoCodigo',
            'Data',
            'HoraInicial',
            'HoraFinal',
            name='uq_granulometry'
        ),
        {"info": {"station_period": ('PeriodoSedimentosInicio', 'PeriodoSedimentosFim')}},
    )

    EstacaoCodigo             = Column(BigInteger, ForeignKey("Estacao.Codigo"), info={"ana": "codigoestacao"})
    """int: station code identifier of the record."""

    NivelConsistencia         = Column(SmallInteger, info={"ana": "Nivel_Consistencia"})
    """
    int: indicates the consistency of the record.
    0 - Raw.
    1 - Consisted.
    """

    Data                      = Column(DateTime, info={"ana": "Data_Dado"})
    """ datetime: date of measurements. """

    HoraInicial               = Column(DateTime, info={"ana": "Hora_Inicial"})
    """ datetime: initial time of the granulometry sampling. """

    HoraFinal                 = Column(DateTime, info={"ana": "Hora_Final"})
    """ datetime: final time of the granulometry sampling. """

    Cota                      = Column(Float, info={"ana": "Cota_cm"})
    """ float: stage during sampling (cm). """

    Largura                   = Column(Float, info={"ana": "Largura_m"})
    """ float: river width during sampling (m). """

    TipoAmostra               = Column(SmallInteger, info={"ana": "Tipo_Amostra"})
    """ int: ANA sample-type code. """

    TipoColeta                = Column(String(50), info={"ana": "Tipo_Coleta"})
    """ string: sampling method (for example IIL, IID, Fundo or Integrada). """

    TipoEquip                 = Column(String(50), info={"ana": "Tipo_Equip"})
    """ string: sampling equipment (for example D-49, DH-48 or Rock Island). """

    ProfTotal                 = Column(Float, info={"ana": "Prof_Total_m"})
    """ float: total sampling depth (m). """

    OrdemColeta               = Column(BigInteger, info={"ana": "Ordem_Coleta"})
    """ int: order of the sample in the sampling campaign. """

    DistPTOInicial            = Column(Float, info={"ana": "Dist_Pto_Inicial_m"})
    """ float: distance from the initial point to the sampling point (m). """

    ChuvaUlt48                = Column(SmallInteger, info={"ana": "Chuva_Ult_48h"})
    """ int: ANA flag indicating whether it rained in the 48 hours before sampling. """

    MatFundo15_9              = Column(Float, info={"ana": "MatFundo_15_9_mm"})
    """ float: percentage of bed material finer than 15.9 mm. """

    MatFundo8_0               = Column(Float, info={"ana": "MatFundo_8_0_mm"})
    """ float: percentage of bed material finer than 8.0 mm. """

    MatFundo4_0               = Column(Float, info={"ana": "MatFundo_4_0_mm"})
    """ float: percentage of bed material finer than 4.0 mm. """

    MatFundo2_0               = Column(Float, info={"ana": "MatFundo_2_0_mm"})
    """ float: percentage of bed material finer than 2.0 mm. """

    MatFundo1_0               = Column(Float, info={"ana": "MatFundo_1_0_mm"})
    """ float: percentage of bed material finer than 1.0 mm. """

    MatFundo0_5               = Column(Float, info={"ana": "MatFundo_0_5_mm"})
    """ float: percentage of bed material finer than 0.5 mm. """

    MatFundo0_25              = Column(Float, info={"ana": "MatFundo_0_25_mm"})
    """ float: percentage of bed material finer than 0.25 mm. """

    MatFundo0_125             = Column(Float, info={"ana": "MatFundo_0_125_mm"})
    """ float: percentage of bed material finer than 0.125 mm. """

    MatFundo0_0625            = Column(Float, info={"ana": "MatFundo_0_625_mm"})
    """ float: percentage of bed material finer than 0.0625 mm. """

    MatFundoArgila            = Column(Float, info={"ana": "MatFundo_Argila_%"})
    """ float: percentage of clay in the bed-material sample. """

    MatFundoSilte             = Column(Float, info={"ana": "MatFundo_Silte_%"})
    """ float: percentage of silt in the bed-material sample. """

    MatFundoAreia             = Column(Float, info={"ana": "MatFundo_Areia_%"})
    """ float: percentage of sand in the bed-material sample. """

    MatFundoPedregulho        = Column(Float, info={"ana": "MatFundo_Pedregulho_%"})
    """ float: percentage of gravel in the bed-material sample. """

    MatFundo0_0_a_0_0156      = Column(Float, info={"ana": "MatFundo_0_0_a_0_0156_mm"})
    """ float: percentage of bed material in the 0.0-0.0156 mm grain-size range. """

    MatFundo0_0157_a_0_02     = Column(Float, info={"ana": "MatFundo_0_0157_a_0_02_mm"})
    """ float: percentage of bed material in the 0.0157-0.02 mm grain-size range. """

    MatFundo0_0201_a_0_0625   = Column(Float, info={"ana": "MatFundo_0_0201_a_0_0625_mm"})
    """ float: percentage of bed material in the 0.0201-0.0625 mm grain-size range. """

    MatFundo0_0626_a_0_1250   = Column(Float, info={"ana": "MatFundo_0_0626_a_0_1250_mm"})
    """ float: percentage of bed material in the 0.0626-0.1250 mm grain-size range. """

    MatFundo0_1251_a_0_25     = Column(Float, info={"ana": "MatFundo_0_1251_a_0_25_mm"})
    """ float: percentage of bed material in the 0.1251-0.25 mm grain-size range. """

    MatFundo0_2501_a_0_5      = Column(Float, info={"ana": "MatFundo_0_2501_a_0_5_mm"})
    """ float: percentage of bed material in the 0.2501-0.5 mm grain-size range. """

    MatFundo0_501_a_1_0       = Column(Float, info={"ana": "MatFundo_0_501_a_1_0_mm"})
    """ float: percentage of bed material in the 0.501-1.0 mm grain-size range. """

    MatFundo1_0001_a_2_0      = Column(Float, info={"ana": "MatFundo_1_0001_a_2_0_mm"})
    """ float: percentage of bed material in the 1.0001-2.0 mm grain-size range. """

    MatFundo2_0001_a_4_0      = Column(Float, info={"ana": "MatFundo_2_0001_a_4_0_mm"})
    """ float: percentage of bed material in the 2.0001-4.0 mm grain-size range. """

    MatFundo4_0001_a_8_0      = Column(Float, info={"ana": "MatFundo_4_0001_a_8_0_mm"})
    """ float: percentage of bed material in the 4.0001-8.0 mm grain-size range. """

    MatFundo8_0001_a_16_000   = Column(Float, info={"ana": "MatFundo_8_0001_a_16_000_mm"})
    """ float: percentage of bed material in the 8.0001-16.000 mm grain-size range. """

    MatFundoD10               = Column(Float, info={"ana": "MatFundo_D10_mm"})
    """ float: bed material grain diameter at which 10% of the sample is finer (mm). """

    MatFundoD16               = Column(Float, info={"ana": "MatFundo_D16_mm"})
    """ float: bed material grain diameter at which 16% of the sample is finer (mm). """

    MatFundoD35               = Column(Float, info={"ana": "MatFundo_D35_mm"})
    """ float: bed material grain diameter at which 35% of the sample is finer (mm). """

    MatFundoD50               = Column(Float, info={"ana": "MatFundo_D50_mm"})
    """ float: bed material grain diameter at which 50% of the sample is finer (mm). """

    MatFundoD65               = Column(Float, info={"ana": "MatFundo_D65_mm"})
    """ float: bed material grain diameter at which 65% of the sample is finer (mm). """

    MatFundoD84               = Column(Float, info={"ana": "MatFundo_D84_mm"})
    """ float: bed material grain diameter at which 84% of the sample is finer (mm). """

    MatFundoD90               = Column(Float, info={"ana": "MatFundo_D90_mm"})
    """ float: bed material grain diameter at which 90% of the sample is finer (mm). """

    MatArrasteVazao           = Column(Float, info={"ana": "MatArraste_Vazao_m3_s"})
    """ float: flow rate during bed-load sampling (m3/s). """

    MatArrasteLargRio         = Column(Float, info={"ana": "MatArraste_LargRio_m"})
    """ float: river width at the bed-load sampling section (m). """

    MatArrasteLargEquip       = Column(Float, info={"ana": "MatArraste_LargEquip_m"})
    """ float: width of the bed-load sampler (m). """

    MatArrastePesoMat         = Column(Float, info={"ana": "MatArraste_PesoMat_g"})
    """ float: mass of bed-load material collected (g). """

    MatArrasteVelMedia        = Column(Float, info={"ana": "MatArraste_VelMedia_m_s"})
    """ float: mean water velocity during bed-load sampling (m/s). """

    MatArrasteTempAgua        = Column(Float, info={"ana": "MatArraste_TempAgua_C"})
    """ float: water temperature during bed-load sampling (C). """

    MatArrasteTempAr          = Column(Float, info={"ana": "MatArraste_TempAr_C"})
    """ float: air temperature during bed-load sampling (C). """

    MatArrasteTempoColeta     = Column(Float, info={"ana": "MatArraste_TempoColeta_min"})
    """ float: bed-load sampling duration (min). """

    MatArrasteArraste         = Column(Float, info={"ana": "MatArraste_Arraste_t_dia"})
    """ float: bed-load transport rate (t/day). """

    MatArraste15_9            = Column(Float, info={"ana": "MatArraste_15_9_mm"})
    """ float: percentage of bed load finer than 15.9 mm. """

    MatArraste8_0             = Column(Float, info={"ana": "MatArraste_8_0_mm"})
    """ float: percentage of bed load finer than 8.0 mm. """

    MatArraste4_0             = Column(Float, info={"ana": "MatArraste_4_0_mm"})
    """ float: percentage of bed load finer than 4.0 mm. """

    MatArraste2_0             = Column(Float, info={"ana": "MatArraste_2_0_mm"})
    """ float: percentage of bed load finer than 2.0 mm. """

    MatArraste1_0             = Column(Float, info={"ana": "MatArraste_1_0_mm"})
    """ float: percentage of bed load finer than 1.0 mm. """

    MatArraste0_5             = Column(Float, info={"ana": "MatArraste_0_5_mm"})
    """ float: percentage of bed load finer than 0.5 mm. """

    MatArraste0_25            = Column(Float, info={"ana": "MatArraste_0_25_mm"})
    """ float: percentage of bed load finer than 0.25 mm. """

    MatArraste0_125           = Column(Float, info={"ana": "MatArraste_0_125_mm"})
    """ float: percentage of bed load finer than 0.125 mm. """

    MatArraste0_0625          = Column(Float, info={"ana": "MatArraste_0_0625_mm"})
    """ float: percentage of bed load finer than 0.0625 mm. """

    MatArrasteArgila          = Column(Float, info={"ana": "MatArraste_Argila_%"})
    """ float: percentage of clay in the bed-load sample. """

    MatArrasteSilte           = Column(Float, info={"ana": "MatArraste_Silte_%"})
    """ float: percentage of silt in the bed-load sample. """

    MatArrasteAreia           = Column(Float, info={"ana": "MatArraste_Areia_%"})
    """ float: percentage of sand in the bed-load sample. """

    MatArrastePedregulho      = Column(Float, info={"ana": "MatArraste_Pedregulho_%"})
    """ float: percentage of gravel in the bed-load sample. """

    MatArraste0_0_a_0_0156    = Column(Float, info={"ana": "MatArraste_0_0_a_0_0156_mm"})
    """ float: percentage of bed load in the 0.0-0.0156 mm grain-size range. """

    MatArraste0_0157_a_0_02   = Column(Float, info={"ana": "MatArraste_0_0157_a_0_02_mm"})
    """ float: percentage of bed load in the 0.0157-0.02 mm grain-size range. """

    MatArraste0_0201_a_0_0625 = Column(Float, info={"ana": "MatArraste_0_0201_a_0_0625_mm"})
    """ float: percentage of bed load in the 0.0201-0.0625 mm grain-size range. """

    MatArraste0_0626_a_0_1250 = Column(Float, info={"ana": "MatArraste_0_0626_a_0_1250_mm"})
    """ float: percentage of bed load in the 0.0626-0.1250 mm grain-size range. """

    MatArraste0_1251_a_0_25   = Column(Float, info={"ana": "MatArraste_0_1251_a_0_25_mm"})
    """ float: percentage of bed load in the 0.1251-0.25 mm grain-size range. """

    MatArraste0_2501_a_0_5    = Column(Float, info={"ana": "MatArraste_0_2501_a_0_5_mm"})
    """ float: percentage of bed load in the 0.2501-0.5 mm grain-size range. """

    MatArraste0_501_a_1_0     = Column(Float, info={"ana": "MatArraste_0_501_a_1_0_mm"})
    """ float: percentage of bed load in the 0.501-1.0 mm grain-size range. """

    MatArraste1_0001_a_2_0    = Column(Float, info={"ana": "MatArraste_1_0001_a_2_0_mm"})
    """ float: percentage of bed load in the 1.0001-2.0 mm grain-size range. """

    MatArraste2_0001_a_4_0    = Column(Float, info={"ana": "MatArraste_2_0001_a_4_0_mm"})
    """ float: percentage of bed load in the 2.0001-4.0 mm grain-size range. """

    MatArraste4_0001_a_8_0    = Column(Float, info={"ana": "MatArraste_4_0001_a_8_0_mm"})
    """ float: percentage of bed load in the 4.0001-8.0 mm grain-size range. """

    MatArraste8_0001_a_16_000 = Column(Float, info={"ana": "MatArraste_8_0001_a_16_000_mm"})
    """ float: percentage of bed load in the 8.0001-16.000 mm grain-size range. """

    MatArrasteD10             = Column(Float, info={"ana": "MatArraste_D10_mm"})
    """ float: bed load grain diameter at which 10% of the sample is finer (mm). """

    MatArrasteD16             = Column(Float, info={"ana": "MatArraste_D16_mm"})
    """ float: bed load grain diameter at which 16% of the sample is finer (mm). """

    MatArrasteD35             = Column(Float, info={"ana": "MatArraste_D35_mm"})
    """ float: bed load grain diameter at which 35% of the sample is finer (mm). """

    MatArrasteD50             = Column(Float, info={"ana": "MatArraste_D50_mm"})
    """ float: bed load grain diameter at which 50% of the sample is finer (mm). """

    MatArrasteD65             = Column(Float, info={"ana": "MatArraste_D65_mm"})
    """ float: bed load grain diameter at which 65% of the sample is finer (mm). """

    MatArrasteD84             = Column(Float, info={"ana": "MatArraste_D84_mm"})
    """ float: bed load grain diameter at which 84% of the sample is finer (mm). """

    MatArrasteD90             = Column(Float, info={"ana": "MatArraste_D90_mm"})
    """ float: bed load grain diameter at which 90% of the sample is finer (mm). """

    MatSusp15_9               = Column(Float, info={"ana": "MatSusp_15_9_mm"})
    """ float: percentage of suspended sediment finer than 15.9 mm. """

    MatSusp8_0                = Column(Float, info={"ana": "MatSusp_8_0_mm"})
    """ float: percentage of suspended sediment finer than 8.0 mm. """

    MatSusp4_0                = Column(Float, info={"ana": "MatSusp_4_0_mm"})
    """ float: percentage of suspended sediment finer than 4.0 mm. """

    MatSusp2_0                = Column(Float, info={"ana": "MatSusp_2_0_mm"})
    """ float: percentage of suspended sediment finer than 2.0 mm. """

    MatSusp1_0                = Column(Float, info={"ana": "MatSusp_1_0_mm"})
    """ float: percentage of suspended sediment finer than 1.0 mm. """

    MatSusp0_5                = Column(Float, info={"ana": "MatSusp_0_5_mm"})
    """ float: percentage of suspended sediment finer than 0.5 mm. """

    MatSusp0_25               = Column(Float, info={"ana": "MatSusp_0_25_mm"})
    """ float: percentage of suspended sediment finer than 0.25 mm. """

    MatSusp0_125              = Column(Float, info={"ana": "MatSusp_0_125_mm"})
    """ float: percentage of suspended sediment finer than 0.125 mm. """

    MatSusp0_0625             = Column(Float, info={"ana": "MatSusp_0_0625_mm"})
    """ float: percentage of suspended sediment finer than 0.0625 mm. """

    MatSuspArgila             = Column(Float, info={"ana": "MatSusp_Argila_%"})
    """ float: percentage of clay in the suspended-sediment sample. """

    MatSuspSilte              = Column(Float, info={"ana": "MatSusp_Silte_%"})
    """ float: percentage of silt in the suspended-sediment sample. """

    MatSuspAreia              = Column(Float, info={"ana": "MatSusp_Areia_%"})
    """ float: percentage of sand in the suspended-sediment sample. """

    MatSuspPedregulho         = Column(Float, info={"ana": "MatSusp_Pedregulho_%"})
    """ float: percentage of gravel in the suspended-sediment sample. """

    MatSusp0_0_a_0_0156       = Column(Float, info={"ana": "MatSusp_0_0_a_0_0156_mm"})
    """ float: percentage of suspended sediment in the 0.0-0.0156 mm grain-size range. """

    MatSusp0_0157_a_0_02      = Column(Float, info={"ana": "MatSusp_0_0157_a_0_02_mm"})
    """ float: percentage of suspended sediment in the 0.0157-0.02 mm grain-size range. """

    MatSusp0_0201_a_0_0625    = Column(Float, info={"ana": "MatSusp_0_0201_a_0_0625_mm"})
    """ float: percentage of suspended sediment in the 0.0201-0.0625 mm grain-size range. """

    MatSusp0_0626_a_0_1250    = Column(Float, info={"ana": "MatSusp_0_0626_a_0_1250_mm"})
    """ float: percentage of suspended sediment in the 0.0626-0.1250 mm grain-size range. """

    MatSusp0_1251_a_0_25      = Column(Float, info={"ana": "MatSusp_0_1251_a_0_25_mm"})
    """ float: percentage of suspended sediment in the 0.1251-0.25 mm grain-size range. """

    MatSusp0_2501_a_0_5       = Column(Float, info={"ana": "MatSusp_0_2501_a_0_5_mm"})
    """ float: percentage of suspended sediment in the 0.2501-0.5 mm grain-size range. """

    MatSusp0_501_a_1_0        = Column(Float, info={"ana": "MatSusp_0_501_a_1_0_mm"})
    """ float: percentage of suspended sediment in the 0.501-1.0 mm grain-size range. """

    MatSusp1_0001_a_2_0       = Column(Float, info={"ana": "MatSusp_1_0001_a_2_0_mm"})
    """ float: percentage of suspended sediment in the 1.0001-2.0 mm grain-size range. """

    MatSusp2_0001_a_4_0       = Column(Float, info={"ana": "MatSusp_2_0001_a_4_0_mm"})
    """ float: percentage of suspended sediment in the 2.0001-4.0 mm grain-size range. """

    MatSusp4_0001_a_8_0       = Column(Float, info={"ana": "MatSusp_4_0001_a_8_0_mm"})
    """ float: percentage of suspended sediment in the 4.0001-8.0 mm grain-size range. """

    MatSusp8_0001_a_16_000    = Column(Float, info={"ana": "MatSusp_8_0001_a_16_000_mm"})
    """ float: percentage of suspended sediment in the 8.0001-16.000 mm grain-size range. """

    MatSuspD10                = Column(Float, info={"ana": "MatSusp_D10_mm"})
    """ float: suspended sediment grain diameter at which 10% of the sample is finer (mm). """

    MatSuspD16                = Column(Float, info={"ana": "MatSusp_D16_mm"})
    """ float: suspended sediment grain diameter at which 16% of the sample is finer (mm). """

    MatSuspD35                = Column(Float, info={"ana": "MatSusp_D35_mm"})
    """ float: suspended sediment grain diameter at which 35% of the sample is finer (mm). """

    MatSuspD50                = Column(Float, info={"ana": "MatSusp_D50_mm"})
    """ float: suspended sediment grain diameter at which 50% of the sample is finer (mm). """

    MatSuspD65                = Column(Float, info={"ana": "MatSusp_D65_mm"})
    """ float: suspended sediment grain diameter at which 65% of the sample is finer (mm). """

    MatSuspD84                = Column(Float, info={"ana": "MatSusp_D84_mm"})
    """ float: suspended sediment grain diameter at which 84% of the sample is finer (mm). """

    MatSuspD90                = Column(Float, info={"ana": "MatSusp_D90_mm"})
    """ float: suspended sediment grain diameter at which 90% of the sample is finer (mm). """




class CrossSection(HidroBaseModel):
    """ Database model for storing Cross Section data. """

    __tablename__ = 'PerfilTransversal'
    __table_args__ = (
        UniqueConstraint('ANA_RegistroID', name='uq_cross_section_ana'),
        {"info": {"station_period": ('PeriodoDescLiquidaInicio', 'PeriodoDescLiquidaFim')}},
    )

    ANA_RegistroID    = Column(Float, info={"ana": "Registro_ID"})
    """ float: ANA record identifier used as the external business key. """

    EstacaoCodigo     = Column(BigInteger, ForeignKey("Estacao.Codigo"), index=True, info={"ana": "codigoestacao"})
    """int: station code identifier of the record."""

    NivelConsistencia = Column(SmallInteger, info={"ana": "Nivel_Consistencia"})
    """
    int: indicates the consistency of the record.
    0 - Raw.
    1 - Consisted.
    """

    Data              = Column(DateTime, info={"ana": "Data_Hora_Medicao"})
    """ datetime: date of measurements. """

    NumLevantamento   = Column(BigInteger, info={"ana": "Num_Levantamento"})
    """ int: cross-section survey number. """

    TipoSecao         = Column(SmallInteger, info={"ana": "Tipo_Secao"})
    """ int: cross-section type.
    1 - Gauge.
    2 - Measurement. """

    NumVerticais      = Column(BigInteger, info={"ana": "Num_Verticais"})
    """ int: number of measured verticals. """

    DistanciaPIPF     = Column(Float, info={"ana": "Distancia_pipf"})
    """ float: distance between the initial (PI) and final (PF) points of the profile (m); PI is on the left bank and PF on the right bank. """

    EixoXDistMaxima   = Column(Float, info={"ana": "Eixo_X_Dist_Maxima"})
    """ float: maximum X-axis distance of the cross-section (m). """

    EixoXDistMinima   = Column(Float, info={"ana": "Eixo_X_Dist_Minima"})
    """ float: minimum X-axis distance of the cross-section (m). """

    EixoYCotaMaxima   = Column(Float, info={"ana": "Eixo_Y_Cota_Maxima"})
    """ float: maximum Y-axis stage of the cross-section (cm). """

    EixoYCotaMinima   = Column(Float, info={"ana": "Eixo_Y_Cota_Minima"})
    """ float: minimum Y-axis stage of the cross-section (cm). """

    ElmGeomPassoCota  = Column(Float, info={"ana": "Elm_Geom_Passo_Cota"})
    """ float: stage step used for the geometric profile elements (cm). """

    Observacoes       = Column(String, info={"ana": "Observacoes"})
    """ string: observations about the cross-section measurement. """




class VerticalCrossSection(HidroBaseModel):
    """ Database model for storing Vertical Cross Section data. """

    __tablename__ = 'PerfilTransversalVert'

    PerfilTransversalID = Column(Integer, ForeignKey("PerfilTransversal.RegistroID"), nullable=False)
    """ int: foreign key to PerfilTransversal.RegistroID. """

    Cota                = Column(Float)
    """ float: stage of the vertical (cm). """

    Distancia           = Column(Float)
    """ float: distance of the vertical from the initial point (m). """


    @classmethod
    def from_json(cls, json_data: dict, perfil_transversal_id: int):
        return cls(
            PerfilTransversalID = perfil_transversal_id,
            Cota                = json_data.get("Cota"),
            Distancia           = json_data.get("Distancia")
        )


class FlowRate(HidroBaseModel):
    """ Database model for storing Flow Rate data.

    Daily values are stored in the generated columns ``Vazao01``..``Vazao31``
    and their statuses in ``Vazao01Status``..``Vazao31Status``.
    """

    __tablename__ = 'Vazoes'
    __table_args__ = (
        UniqueConstraint(
            'EstacaoCodigo',
            'Data',
            name='uq_flow_rate'
        ),
        {"info": {"station_period": ('PeriodoDescLiquidaInicio', 'PeriodoDescLiquidaFim')}},
    )

    EstacaoCodigo        = Column(BigInteger, ForeignKey("Estacao.Codigo"), info={"ana": "codigoestacao"})
    """int: station code identifier of the record."""

    NivelConsistencia    = Column(SmallInteger, info={"ana": "Nivel_Consistencia"})
    """
    int: indicates the consistency of the record.
    0 - Raw.
    1 - Consisted.
    """

    Data                 = Column(DateTime, info={"ana": "Data_Hora_Dado"})
    """ datetime: date of measurements. """
    
    MediaDiaria          = Column(SmallInteger, info={"ana": "Mediadiaria"})
    """ int: indicates whether the measurement is a daily average.
    0 - No (instantaneous).
    1 - Yes (daily average). """

    MetodoObtencaoVazoes = Column(SmallInteger, info={"ana": "Metodo_Obtencao_Vazoes"})
    """ int: indicates how the flow rate was obtained.
    1 - Rating curve.
    2 - Transfer.
    3 - Sum.
    4 - ADCP. """

    Maxima               = Column(Float, info={"ana": "Maxima"})
    """ float: maximum flow rate in the month (m3/s). """

    Minima               = Column(Float, info={"ana": "Minima"})
    """ float: minimum flow rate in the month (m3/s). """

    Media                = Column(Float, info={"ana": "Media"})
    """ float: average flow rate in the month (m3/s). """

    DiaMaxima            = Column(SmallInteger, info={"ana": "Dia_Maxima"})
    """ int: day of the month when the maximum flow rate occurred. """

    DiaMinima            = Column(SmallInteger, info={"ana": "Dia_Minima"})
    """ int: day of the month when the minimum flow rate occurred. """

    MaximaStatus         = Column(SmallInteger, info={"ana": "Maxima_Status"})
    """ int: indicate availability, precision and reliability of the value.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Dry gauge. """

    MinimaStatus         = Column(SmallInteger, info={"ana": "Minima_Status"})
    """ int: indicate availability, precision and reliability of the value.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Dry gauge. """

    MediaStatus          = Column(SmallInteger, info={"ana": "Media_Status"})
    """ int: indicate availability, precision and reliability of the value.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Dry gauge. """

    MediaAnual           = Column(Float, info={"ana": "Media_Anual"})
    """ float: average flow rate in the year (m3/s). """

    MediaAnualStatus     = Column(SmallInteger, info={"ana": "Media_Anual_Status"})
    """ int: indicate availability, precision and reliability of the value.
    0 - No value.
    1 - Real value.
    2 - Estimated value.
    3 - Doubtful value.
    4 - Dry gauge. """

    # Hora                 = Column(DateTime)


    for i in range(1, 32):
        locals()[f'Vazao{i:02d}'] = Column(f'Vazao{i:02d}', Float, info={"ana": f"Vazao_{i:02d}"})
        locals()[f'Vazao{i:02d}Status'] = Column(f'Vazao{i:02d}Status', SmallInteger, info={"ana": f"Vazao_{i:02d}_Status"})


class Telemetry(HidroBaseModel):
    """ Database model for storing telemetric series data.

    The detailed endpoint is the superset of the adopted endpoint, so both
    payloads share this table. Adopted-only records leave the detailed-only
    columns null.
    """

    __tablename__ = 'Telemetria'
    __table_args__ = (
        UniqueConstraint(
            'EstacaoCodigo',
            'Data_Hora_Medicao',
            name='uq_telemetry',
        ),
    )

    EstacaoCodigo              = Column(BigInteger, ForeignKey("Estacao.Codigo"), info={"ana": "codigoestacao"})
    """int: station code identifier of the record."""

    Data_Hora_Medicao          = Column(DateTime, info={"ana": "Data_Hora_Medicao"})
    """datetime: date and time of the measurement."""

    Data_Atualizacao           = Column(DateTime, info={"ana": "Data_Atualizacao"})
    """datetime: date and time the measurement was last updated."""

    Bateria                    = Column(Float, info={"ana": "Bateria"})
    """float: battery voltage."""

    Chuva_Acumulada            = Column(Float, info={"ana": "Chuva_Acumulada"})
    """float: accumulated rainfall (mm)."""

    Chuva_Acumulada_Status     = Column(SmallInteger, info={"ana": "Chuva_Acumulada_Status"})
    """int: availability/reliability status of accumulated rainfall."""

    Chuva_Adotada              = Column(Float, info={"ana": "Chuva_Adotada"})
    """float: adopted rainfall (mm)."""

    Chuva_Adotada_Status       = Column(SmallInteger, info={"ana": "Chuva_Adotada_Status"})
    """int: availability/reliability status of adopted rainfall."""

    Cota_Adotada               = Column(Float, info={"ana": "Cota_Adotada"})
    """float: adopted stage (cm)."""

    Cota_Adotada_Status        = Column(SmallInteger, info={"ana": "Cota_Adotada_Status"})
    """int: availability/reliability status of adopted stage."""

    Cota_Display               = Column(Float, info={"ana": "Cota_Display"})
    """float: displayed stage (cm)."""

    Cota_Display_Status        = Column(SmallInteger, info={"ana": "Cota_Display_Status"})
    """int: availability/reliability status of displayed stage."""

    Cota_Manual                = Column(Float, info={"ana": "Cota_Manual"})
    """float: manual stage (cm)."""

    Cota_Manual_Status         = Column(SmallInteger, info={"ana": "Cota_Manual_Status"})
    """int: availability/reliability status of manual stage."""

    Cota_Sensor                = Column(Float, info={"ana": "Cota_Sensor"})
    """float: stage measured by the sensor (cm)."""

    Cota_Sensor_Status         = Column(SmallInteger, info={"ana": "Cota_Sensor_Status"})
    """int: availability/reliability status of sensor stage."""

    Pressao_Atmosferica        = Column(Float, info={"ana": "Pressao_Atmosferica"})
    """float: atmospheric pressure."""

    Pressao_Atmosferica_Status = Column(SmallInteger, info={"ana": "Pressao_Atmosferica_Status"})
    """int: availability/reliability status of atmospheric pressure."""

    Temperatura_Agua           = Column(Float, info={"ana": "Temperatura_Agua"})
    """float: water temperature."""

    Temperatura_Agua_Status    = Column(SmallInteger, info={"ana": "Temperatura_Agua_Status"})
    """int: availability/reliability status of water temperature."""

    Temperatura_Interna        = Column(Float, info={"ana": "Temperatura_Interna"})
    """float: internal temperature."""

    Vazao_Adotada              = Column(Float, info={"ana": "Vazao_Adotada"})
    """float: adopted flow rate (m3/s)."""

    Vazao_Adotada_Status       = Column(SmallInteger, info={"ana": "Vazao_Adotada_Status"})
    """int: availability/reliability status of adopted flow rate."""
