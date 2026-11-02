"""Agente de atendimento: Gemini com function calling sobre as ferramentas da loja."""

import functools
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from src.policies import consultar_politica
from src.prompts import montar_system_prompt
from src.tools import FERRAMENTAS, data_referencia

MODELO_PADRAO = "gemini-3.5-flash"
# No plano gratuito cada modelo tem cota diária própria (~20 requisições). Quando a cota de um
# acaba ou ele fica sobrecarregado, o agente segue a conversa com o próximo da lista.
MODELOS_RESERVA_PADRAO = "gemini-3.5-flash-lite,gemini-3.7-flash,gemini-3.1-flash-lite"
MAX_CHAMADAS_FERRAMENTAS = 8
TIMEOUT_MS = 30_000
# Erros transitórios (limite por minuto, sobrecarga, tempo esgotado): vale esperar e tentar de novo.
CODIGOS_TRANSITORIOS = {429, 500, 503, 504}
ESPERAS_ENTRE_TENTATIVAS = [2, 5]


@dataclass
class Resposta:
    texto: str
    ferramentas: list[str] = field(default_factory=list)


def _cota_diaria_esgotada(erro: errors.APIError) -> bool:
    return erro.code == 429 and "per day" in str(erro.message).lower()


class AgenteEmporio:
    def __init__(self, modelo: str | None = None, ao_evento=None):
        """ao_evento: função opcional chamada a cada evento (tool chamada, nova tentativa, troca de modelo)."""
        load_dotenv()
        self._ao_evento = ao_evento
        principal = modelo or os.getenv("MODEL", MODELO_PADRAO)
        reservas = os.getenv("MODELOS_RESERVA", MODELOS_RESERVA_PADRAO).split(",")
        self._modelos = list(dict.fromkeys([principal, *(m.strip() for m in reservas if m.strip())]))
        self._indice_modelo = 0
        self._client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=TIMEOUT_MS),
        )
        self._chamadas: list[str] = []
        self.nova_conversa()

    @property
    def modelo(self) -> str:
        return self._modelos[self._indice_modelo]

    def _evento(self, descricao: str) -> None:
        self._chamadas.append(descricao)
        if self._ao_evento:
            self._ao_evento(descricao)

    def _registrar(self, funcao):
        """Envolve a ferramenta para registrar cada chamada (nome + argumentos) para log e depuração.

        functools.wraps preserva nome, docstring e assinatura, que o SDK usa para montar o schema da tool.
        """
        @functools.wraps(funcao)
        def envolvida(*args, **kwargs):
            argumentos = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            self._evento(f"{funcao.__name__}({argumentos})")
            return funcao(*args, **kwargs)
        return envolvida

    def nova_conversa(self) -> None:
        # A data de referência (DATA_REFERENCIA) permite simular cenários; a hora é sempre a atual.
        agora = datetime.combine(data_referencia(), datetime.now().time())
        self._config = types.GenerateContentConfig(
            system_instruction=montar_system_prompt(agora),
            tools=[self._registrar(f) for f in [*FERRAMENTAS, consultar_politica]],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=MAX_CHAMADAS_FERRAMENTAS
            ),
            temperature=0.3,
        )
        # O objeto de chat mantém o histórico da conversa (memória dentro da sessão).
        self._chat = self._client.chats.create(model=self.modelo, config=self._config)

    def _trocar_modelo(self) -> bool:
        """Passa para o próximo modelo da lista, levando o histórico da conversa."""
        if self._indice_modelo + 1 >= len(self._modelos):
            return False
        historico = self._chat.get_history()
        self._indice_modelo += 1
        self._chat = self._client.chats.create(model=self.modelo, config=self._config, history=historico)
        self._evento(f"[trocando para o modelo {self.modelo}]")
        return True

    def _enviar(self, mensagem: str):
        """Envia a mensagem com novas tentativas para erros transitórios e troca de modelo como último recurso."""
        while True:
            for espera in [*ESPERAS_ENTRE_TENTATIVAS, None]:
                try:
                    return self._chat.send_message(mensagem)
                except errors.APIError as erro:
                    if erro.code not in CODIGOS_TRANSITORIOS:
                        raise
                    ultimo_erro = erro
                    if _cota_diaria_esgotada(erro) or espera is None:
                        motivo = "cota diária esgotada" if _cota_diaria_esgotada(erro) else f"API {erro.code}"
                        self._evento(f"[{self.modelo}: {motivo}]")
                        break  # esperar não resolve: tenta outro modelo
                    self._evento(f"[API {erro.code} no {self.modelo}, nova tentativa em {espera}s]")
                    time.sleep(espera)
            if not self._trocar_modelo():
                raise ultimo_erro

    def responder(self, mensagem: str) -> Resposta:
        self._chamadas = []
        try:
            resposta = self._enviar(mensagem)
        except errors.APIError as erro:
            texto = "Tive um problema técnico aqui e não consegui consultar o sistema. Pode tentar de novo em instantes?"
            return Resposta(texto=texto, ferramentas=[*self._chamadas, f"ERRO API {erro.code}: {erro.message}"])

        texto = (resposta.text or "").strip()
        if not texto:
            texto = "Desculpe, não consegui formular uma resposta agora. Pode reformular sua pergunta?"
        return Resposta(texto=texto, ferramentas=list(self._chamadas))
