"""Agente de atendimento: Gemini com function calling sobre as ferramentas da loja.

O laço de ferramentas (modelo pede uma ferramenta -> código executa -> resultado volta ao modelo)
é feito aqui, passo a passo, em vez do modo automático do SDK. Motivo: no plano gratuito a API falha
com frequência no meio desse laço; no modo automático uma falha descarta tudo, inclusive o resultado
das ferramentas já executadas, e o modelo chegou a responder com preços inventados. Aqui cada passo
é repetido isoladamente e o que já foi consultado continua na conversa.
"""

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx
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
# Falhas de rede (ex.: tempo de leitura esgotado) chegam como exceções do httpx, não como APIError.
ERROS_DE_REDE = (httpx.TimeoutException, httpx.NetworkError)

# Verificação anti-alucinação: valores em reais numa resposta sem nenhuma ferramenta consultada
# na conversa só podem ter sido inventados.
PADRAO_VALOR = re.compile(r"R\$\s?\d")
PEDIDO_DE_REVISAO = (
    "[Verificação automática do sistema, não escrita pelo cliente] A resposta anterior citou valores "
    "sem consultar nenhuma ferramenta. Consulte as ferramentas e responda de novo à última pergunta "
    "do cliente, sem inventar valores."
)


@dataclass
class Resposta:
    texto: str
    ferramentas: list[str] = field(default_factory=list)


def _descrever(erro: Exception) -> str:
    if isinstance(erro, errors.APIError):
        return f"API {erro.code}"
    return f"rede: {type(erro).__name__}"


def _transitorio(erro: Exception) -> bool:
    return isinstance(erro, ERROS_DE_REDE) or (isinstance(erro, errors.APIError) and erro.code in CODIGOS_TRANSITORIOS)


def _cota_diaria_esgotada(erro: Exception) -> bool:
    return isinstance(erro, errors.APIError) and erro.code == 429 and "per day" in str(erro.message).lower()


def _usou_ferramentas(conteudos: list[types.Content]) -> bool:
    return any(parte.function_response for c in conteudos for parte in (c.parts or []))


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
        self._ferramentas = {f.__name__: f for f in [*FERRAMENTAS, consultar_politica]}
        self._chamadas: list[str] = []
        self.modelos_usados: list[str] = []  # modelos que de fato geraram respostas, na ordem em que entraram
        self.nova_conversa()

    @property
    def modelo(self) -> str:
        return self._modelos[self._indice_modelo]

    def _evento(self, descricao: str) -> None:
        self._chamadas.append(descricao)
        if self._ao_evento:
            self._ao_evento(descricao)

    def nova_conversa(self) -> None:
        # A data de referência (DATA_REFERENCIA) permite simular cenários; a hora é sempre a atual.
        agora = datetime.combine(data_referencia(), datetime.now().time())
        self._config = types.GenerateContentConfig(
            system_instruction=montar_system_prompt(agora),
            # O SDK monta o schema de cada ferramenta a partir do nome, docstring e tipos da função.
            tools=list(self._ferramentas.values()),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.3,
        )
        # Histórico da conversa (memória dentro da sessão): mensagens, pedidos de ferramenta e resultados.
        self._historico: list[types.Content] = []

    def _trocar_modelo(self) -> bool:
        """Passa para o próximo modelo da lista. O histórico é nosso, então segue intacto."""
        if self._indice_modelo + 1 >= len(self._modelos):
            return False
        self._indice_modelo += 1
        self._evento(f"[trocando para o modelo {self.modelo}]")
        return True

    def _gerar(self, conteudos: list[types.Content]) -> types.GenerateContentResponse:
        """Um passo do modelo, com novas tentativas para erros transitórios e troca de modelo como último recurso."""
        while True:
            for espera in [*ESPERAS_ENTRE_TENTATIVAS, None]:
                try:
                    resposta = self._client.models.generate_content(model=self.modelo, contents=conteudos, config=self._config)
                    if self.modelo not in self.modelos_usados:
                        self.modelos_usados.append(self.modelo)
                    return resposta
                except (errors.APIError, *ERROS_DE_REDE) as erro:
                    if not _transitorio(erro):
                        raise
                    ultimo_erro = erro
                    if _cota_diaria_esgotada(erro) or espera is None:
                        motivo = "cota diária esgotada" if _cota_diaria_esgotada(erro) else _descrever(erro)
                        self._evento(f"[{self.modelo}: {motivo}]")
                        break  # esperar não resolve: tenta outro modelo
                    self._evento(f"[{_descrever(erro)} no {self.modelo}, nova tentativa em {espera}s]")
                    time.sleep(espera)
            if not self._trocar_modelo():
                raise ultimo_erro

    def _executar(self, chamada: types.FunctionCall) -> types.Part:
        argumentos = dict(chamada.args or {})
        self._evento(f"{chamada.name}({', '.join(f'{k}={v!r}' for k, v in argumentos.items())})")
        funcao = self._ferramentas.get(chamada.name)
        try:
            resultado = funcao(**argumentos) if funcao else {"erro": f"Ferramenta {chamada.name} não existe."}
        except TypeError as erro:  # argumentos inválidos vindos do modelo
            resultado = {"erro": f"Argumentos inválidos: {erro}"}
        return types.Part.from_function_response(name=chamada.name, response={"resultado": resultado})

    def _conversar(self, mensagem: str) -> str:
        conteudos = [*self._historico, types.Content(role="user", parts=[types.Part.from_text(text=mensagem)])]
        revisou = False
        for _ in range(MAX_CHAMADAS_FERRAMENTAS + 1):
            resposta = self._gerar(conteudos)
            candidato = resposta.candidates[0].content if resposta.candidates else None
            if candidato is None:
                break
            conteudos.append(candidato)

            if resposta.function_calls:
                # Os resultados entram na lista local: se o próximo passo falhar, nada do que foi consultado se perde.
                conteudos.append(types.Content(role="user", parts=[self._executar(c) for c in resposta.function_calls]))
                continue

            texto = (resposta.text or "").strip()
            if PADRAO_VALOR.search(texto) and not _usou_ferramentas(conteudos) and not revisou:
                self._evento("[verificação: valores citados sem consulta, pedindo nova resposta]")
                conteudos.append(types.Content(role="user", parts=[types.Part.from_text(text=PEDIDO_DE_REVISAO)]))
                revisou = True
                continue

            self._historico = conteudos  # só uma resposta completa entra na memória da conversa
            return texto
        return ""

    def responder(self, mensagem: str) -> Resposta:
        self._chamadas = []
        try:
            texto = self._conversar(mensagem)
        except (errors.APIError, *ERROS_DE_REDE) as erro:
            texto = "Tive um problema técnico aqui e não consegui consultar o sistema. Pode tentar de novo em instantes?"
            return Resposta(texto=texto, ferramentas=[*self._chamadas, f"ERRO API ({_descrever(erro)}): {erro}"])

        if not texto:
            texto = "Desculpe, não consegui formular uma resposta agora. Pode reformular sua pergunta?"
        return Resposta(texto=texto, ferramentas=list(self._chamadas))
