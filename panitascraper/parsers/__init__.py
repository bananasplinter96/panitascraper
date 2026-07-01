from .encuentralos import parse as parse_encuentralos
from .reencuentrohelp import parse as parse_reencuentrohelp
from .busquedaunificadavzla import parse as parse_busquedaunificadavzla
from .busquedavzla import parse as parse_busquedavzla
from .tebusco import parse as parse_tebusco
from .localizadosvenezuela import parse as parse_localizadosvenezuela
from .localizapacientes import parse as parse_localizapacientes
from .sismo_ehr import parse as parse_sismo_ehr
from .busquedavzla_sheet import parse as parse_busquedavzla_sheet
from .drive_sismo_vzla import parse as parse_drive_sismo_vzla
from .ubicame import parse as parse_ubicame
from .ucv_aparecidos import parse as parse_ucv_aparecidos
from .aquiestoyvenezuela import parse as parse_aquiestoyvenezuela
from .reportevenezuela import parse as parse_reportevenezuela
from .hospitalesdevenezuela import parse as parse_hospitalesdevenezuela
from .osirisberbesia import parse as parse_osirisberbesia

PARSERS = {
    "encuentralos": parse_encuentralos,
    "reencuentrohelp": parse_reencuentrohelp,
    "busquedaunificadavzla": parse_busquedaunificadavzla,
    "busquedavzla": parse_busquedavzla,
    "tebusco": parse_tebusco,
    "localizadosvenezuela": parse_localizadosvenezuela,
    "localizapacientes": parse_localizapacientes,
    "sismo_ehr": parse_sismo_ehr,
    "busquedavzla_sheet": parse_busquedavzla_sheet,
    "drive_sismo_vzla": parse_drive_sismo_vzla,
    "ubicame": parse_ubicame,
    "ucv_aparecidos": parse_ucv_aparecidos,
    "aquiestoyvenezuela": parse_aquiestoyvenezuela,
    "reportevenezuela": parse_reportevenezuela,
    "hospitalesdevenezuela": parse_hospitalesdevenezuela,
    "osirisberbesia": parse_osirisberbesia,
}
