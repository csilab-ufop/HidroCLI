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

"""
Provides request functionalities to ANA HidroWebservices API
"""

import os, requests, json, time, logging
logger = logging.getLogger(__name__)

from datetime import datetime

_DATA_ENDPOINTS_MAP = {
    "Bacia":             "/EstacoesTelemetricas/HidroBacia/v1",
    "SubBacia":          "/EstacoesTelemetricas/HidroSubBacia/v1",
    "Entidade":          "/EstacoesTelemetricas/HidroEntidade/v1",
    "Municipio":         "/EstacoesTelemetricas/HidroMunicipio/v1",
    "Rio":               "/EstacoesTelemetricas/HidroRio/v1",
    "Estado":            "/EstacoesTelemetricas/HidroUF/v1",
    "Estacao":           "/EstacoesTelemetricas/HidroInventarioEstacoes/v1",
    "Chuvas":            "/EstacoesTelemetricas/HidroSerieChuva/v1",
    "ResumoDescarga":    "/EstacoesTelemetricas/HidroSerieResumoDescarga/v1",
    "CurvaDescarga":     "/EstacoesTelemetricas/HidroSerieCurvaDescarga/v1",
    "Sedimentos":        "/EstacoesTelemetricas/HidroSerieSedimentos/v1",
    "QualAgua":          "/EstacoesTelemetricas/HidroSerieQA/v1",
    "Cotas":             "/EstacoesTelemetricas/HidroSerieCotas/v1",
    "Granulometria":     "/EstacoesTelemetricas/HidroSerieGranulometria/v1",
    "PerfilTransversal": "/EstacoesTelemetricas/HidroSeriePerfilTransversal/v1",
    "Vazoes":            "/EstacoesTelemetricas/HidroSerieVazao/v1",
    "Telemetria":        "/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaDetalhada/v1"
}

_BASE_JOBS = {"Bacia", "SubBacia", "Entidade", "Municipio", "Rio", "Estado"}


def _request_hidro_ws(endpoint, headers, params={}):
    """ Make a request to ANA API and returns the json.

    :raises requests.exceptions.HTTPError: when the API returns a non-2xx
        status.
    :raises requests.exceptions.RequestException: when the request fails due
        to a network/connection error.
    """

    url = "https://www.ana.gov.br/hidrowebservice"
    logger.verbose(f"[REQUEST]: Endpoint: {endpoint}\nHeaders: {headers}\nParams: {params}")
    try:
        response = requests.get(f"{url}{endpoint}", headers=headers, params=params, timeout=(10, 120))
    except requests.exceptions.RequestException as e:
        if isinstance(e, requests.exceptions.Timeout):
            logger.verbose(
                f"[REQUEST]: timeout {type(e).__name__} for {endpoint}, "
                f"params: {params}: {e}"
            )
        elif isinstance(e, (requests.exceptions.SSLError,
                            requests.exceptions.ConnectionError,
                            requests.exceptions.ChunkedEncodingError,
                            requests.exceptions.ContentDecodingError)):
            logger.trace(
                f"[REQUEST]: {type(e).__name__} for {endpoint}, "
                f"params: {params}: {e}"
            )
        else:
            logger.error(
                f"[REQUEST]: unhandled {type(e).__name__} for {endpoint}, "
                f"params: {params}: {e}"
            )
        raise
    if response.ok:
        try:
            return response.json()
        except Exception as e:
            logger.error(f"[REQUEST]: (exception): {e}")
    else:
        try:
            body = response.json()
        except Exception:
            body = None
        logger.trace(
            f"[REQUEST]: HTTP {response.status_code} for {endpoint}, "
            f"params: {params}, body: {body}"
        )
        raise requests.exceptions.HTTPError(
            f"{response.status_code}", response=response,
        )

def request_token(client_id: str, client_password: str, max_retries=3, retry_delay=2):
    """ Request an token to ANA API and returns it.

    A 429 or 5xx response is re-raised immediately so the caller can throttle
    the request pool without retrying the token endpoint.
    """

    headers = {
        "accept":        "*/*",
        "Identificador": f"{client_id}",
        "Senha":         f"{client_password}",
    }
    endpoint = "/EstacoesTelemetricas/OAUth/v1"
    last_error = None
    for attempt in range(max_retries):
        try:
            data = _request_hidro_ws(endpoint, headers, {})
            token           = data.get("items", {}).get("tokenautenticacao")
            expires_RFC2822 = data.get("items", {}).get("validade")
            expires_ISOND   = datetime.strptime(expires_RFC2822, "%a %b %d %H:%M:%S GMT-03:00 %Y")
            return [token, expires_ISOND]
        except Exception as e:
            if isinstance(e, requests.exceptions.HTTPError):
                response = e.response
                status = response.status_code if response is not None else None
                if status == 429 or (status is not None and 500 <= status < 600):
                    raise
            last_error = e
            logger.trace(f"[TOKEN]: (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

    raise Exception(f"Failed after {max_retries} attempts") from last_error


def request_job_data(job_name: str, token: str, params: dict,
                     save_json: bool = False,
                     json_dir: str = "json",
                     read_json: bool = False) -> (bool, dict):
    """ Request data to ANA API and returns it.

    When ``read_json`` is true, a payload previously saved under ``json_dir``
    is returned without contacting the API. Missing or unreadable payloads
    fall back to the API.

    When ``save_json`` is true, payloads fetched from the API are also written
    under ``json_dir`` following :func:`_json_file_path`.

    :returns: ``(True, items)`` on success, ``(False, [])`` on a request
        failure.

    :raises requests.exceptions.HTTPError: when the API returns a non-2xx
        status, propagated from :func:`_request_hidro_ws`.
    """

    if read_json:
        try:
            return (True, _load_response(job_name, params, json_dir))
        except FileNotFoundError:
            logger.verbose(f"[REQUEST_DATA]: (load): {job_name}: not found, requesting from API")
        except Exception as e:
            logger.warning(f"[REQUEST_DATA]: (load): {job_name}: {e}, requesting from API")

    headers = {
        "accept":        "*/*",
        "Authorization": f"Bearer {token}"
    }
    endpoint = _DATA_ENDPOINTS_MAP[job_name]
    response = _request_hidro_ws(endpoint, headers, params)
    try:
        items = response.get("items", {})
    except Exception as e:
        logger.verbose(f"[REQUEST_DATA]: (exception): {e}")
        return (False, [])

    if save_json:
        try:
            _save_response(job_name, params, items, json_dir)
        except Exception as e:
            logger.warning(f"[REQUEST_DATA]: (save): {job_name}: {e}")

    return (True, items)


def _json_file_path(job_name: str, params: dict, json_dir: str) -> str:
    """ Return the file path where a job payload is saved under ``json_dir``.

    The layout mirrors the repository's ``json/`` directory:

    - base jobs: ``<dir>/<Job>.json``
    - ``Estacao``: ``<dir>/Estacao/Estacao_<UF>.json``
    - series jobs: ``<dir>/<Job>/station_<code>_<start>_<end>.json``
    - telemetry: ``<dir>/Telemetria/station_<code>_<date>_<range>.json``
    """

    if job_name == "Telemetria":
        station = params["Código da Estação"]
        date    = params["Data de Busca (yyyy-MM-dd)"]
        range_  = params["Range Intervalo de busca"]
        return os.path.join(
            json_dir, job_name, f"station_{station}_{date}_{range_}.json"
        )
    if job_name == "Estacao":
        uf = params["Unidade Federativa"]
        return os.path.join(json_dir, job_name, f"{job_name}_{uf}.json")
    if job_name in _BASE_JOBS:
        return os.path.join(json_dir, f"{job_name}.json")

    station = params["Código da Estação"]
    start   = params["Data Inicial (yyyy-MM-dd)"]
    end     = params["Data Final (yyyy-MM-dd)"]
    return os.path.join(
        json_dir, job_name, f"station_{station}_{start}_{end}.json"
    )


def _load_response(job_name: str, params: dict, json_dir: str):
    """ Load a job payload saved under ``json_dir`` and return it. """

    path = _json_file_path(job_name, params, json_dir)
    with open(path) as f:
        items = json.load(f)
    logger.verbose(f"[REQUEST_DATA]: Loaded {path}")
    return items


def _save_response(job_name: str, params: dict, items, json_dir: str) -> str:
    """ Save a job payload under ``json_dir`` and return the written path."""

    path      = _json_file_path(job_name, params, json_dir)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    logger.verbose(f"[REQUEST_DATA]: Saved {path}")
    return path


