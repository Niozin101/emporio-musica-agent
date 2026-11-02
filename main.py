"""CLI do agente de atendimento da Empório da Música.

Uso:
    python main.py                       # conversa interativa
    python main.py --debug               # mostra as ferramentas chamadas a cada resposta
    python main.py --roteiro arquivo.txt # envia as mensagens do arquivo (uma por linha) e salva a conversa
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from src.agent import AgenteEmporio

PASTA_CONVERSAS = Path(__file__).resolve().parent / "logs" / "conversas"


class Transcricao:
    """Salva cada conversa em Markdown (útil para auditoria e para gerar os exemplos do repositório)."""

    def __init__(self, modelo: str):
        PASTA_CONVERSAS.mkdir(parents=True, exist_ok=True)
        self.arquivo = PASTA_CONVERSAS / f"{datetime.now():%Y%m%d-%H%M%S}.md"
        self._escrever(f"# Conversa com a Lia (Empório da Música)\n\n_Modelo: {modelo} | {datetime.now():%d/%m/%Y %H:%M}_\n")

    def _escrever(self, texto: str) -> None:
        with open(self.arquivo, "a", encoding="utf-8") as f:
            f.write(texto + "\n")

    def registrar(self, mensagem: str, resposta) -> None:
        self._escrever(f"**Cliente:** {mensagem}\n")
        if resposta.ferramentas:
            chamadas = "\n".join(f"> 🔧 `{c}`" for c in resposta.ferramentas)
            self._escrever(chamadas + "\n")
        self._escrever(f"**Lia:** {resposta.texto}\n")


def conversar(agente: AgenteEmporio, mensagens, debug: bool) -> None:
    transcricao = Transcricao(agente.modelo)
    for mensagem in mensagens:
        mensagem = mensagem.strip()
        if not mensagem:
            continue
        if mensagem.lower() in {"/sair", "sair"}:
            break
        if mensagem.lower() == "/nova":
            agente.nova_conversa()
            transcricao = Transcricao(agente.modelo)
            print("(nova conversa iniciada)\n")
            continue

        resposta = agente.responder(mensagem)
        if debug:
            for chamada in resposta.ferramentas:
                print(f"  🔧 {chamada}")
        print(f"Lia: {resposta.texto}\n")
        transcricao.registrar(mensagem, resposta)
    print(f"(conversa salva em {transcricao.arquivo})")


def mensagens_interativas():
    while True:
        try:
            yield input("Você: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Atendimento virtual da Empório da Música")
    parser.add_argument("--debug", action="store_true", help="mostra as ferramentas chamadas")
    parser.add_argument("--roteiro", type=Path, help="arquivo com uma mensagem do cliente por linha")
    args = parser.parse_args()

    agente = AgenteEmporio()
    if args.roteiro:
        # utf-8-sig ignora o BOM que alguns editores do Windows colocam no início do arquivo.
        linhas = args.roteiro.read_text(encoding="utf-8-sig").splitlines()
        def ecoar():
            for linha in linhas:
                if linha.strip():
                    print(f"Você: {linha}")
                    yield linha
        conversar(agente, ecoar(), debug=True)
    else:
        print("Lia, da Empório da Música 🎸  (digite /nova para recomeçar ou /sair para encerrar)\n")
        conversar(agente, mensagens_interativas(), debug=args.debug)


if __name__ == "__main__":
    main()
