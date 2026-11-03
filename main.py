"""CLI do agente de atendimento da Empório da Música.

Uso:
    python main.py                       # conversa interativa
    python main.py --debug               # mostra as ferramentas chamadas a cada resposta
    python main.py --roteiro arquivo.txt # roda uma conversa pronta e salva o resultado em examples/

Formato do roteiro: uma mensagem do cliente por linha. Linhas iniciadas por "#" são metadados:
    # titulo: Devolução por arrependimento
    # data_referencia: 2026-02-20   (opcional: data usada como "hoje")
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from src.agent import AgenteEmporio

RAIZ = Path(__file__).resolve().parent
PASTA_CONVERSAS = RAIZ / "logs" / "conversas"
PASTA_EXEMPLOS = RAIZ / "examples"


class Transcricao:
    """Salva cada conversa em Markdown (útil para auditoria e para gerar os exemplos do repositório)."""

    def __init__(self, modelo: str, arquivo: Path | None = None, titulo: str = "Conversa com a Lia (Empório da Música)"):
        self.arquivo = arquivo or PASTA_CONVERSAS / f"{datetime.now():%Y%m%d-%H%M%S}.md"
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo.write_text("", encoding="utf-8")
        cabecalho = f"_Modelo principal: {modelo} | Gerado em {datetime.now():%d/%m/%Y %H:%M}"
        if os.getenv("DATA_REFERENCIA"):
            cabecalho += f" | Data de referência simulada: {os.environ['DATA_REFERENCIA']}"
        self._escrever(f"# {titulo}\n\n{cabecalho}_\n\n> 🔧 indica as ferramentas que o agente chamou para responder.\n")

    def _escrever(self, texto: str) -> None:
        with open(self.arquivo, "a", encoding="utf-8") as f:
            f.write(texto + "\n")

    def registrar(self, mensagem: str, resposta) -> None:
        self._escrever(f"**Cliente:** {mensagem}\n")
        if resposta.ferramentas:
            # Dois espaços no fim da linha = quebra de linha no Markdown (senão as linhas se juntam).
            chamadas = "  \n".join(f"> 🔧 `{c}`" for c in resposta.ferramentas)
            self._escrever(chamadas + "\n")
        self._escrever(f"**Lia:** {resposta.texto}\n")

    def finalizar(self, modelos_usados: list[str]) -> None:
        if modelos_usados:
            self._escrever(f"---\n\n_Modelos que geraram as respostas: {', '.join(modelos_usados)}_")


def conversar(agente: AgenteEmporio, mensagens, transcricao: Transcricao) -> int:
    """Conduz a conversa e devolve quantas respostas falharam por erro da API."""
    falhas = 0
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

        print("  (Lia está digitando...)", flush=True)
        try:
            resposta = agente.responder(mensagem)
        except KeyboardInterrupt:
            print("\n(interrompido)")
            break
        falhas += any(f.startswith("ERRO API") for f in resposta.ferramentas)
        print(f"Lia: {resposta.texto}\n")
        transcricao.registrar(mensagem, resposta)
    transcricao.finalizar(agente.modelos_usados)
    print(f"(conversa salva em {transcricao.arquivo})")
    return falhas


def ler_roteiro(caminho: Path) -> tuple[dict, list[str]]:
    # utf-8-sig ignora o BOM que alguns editores do Windows colocam no início do arquivo.
    metadados, mensagens = {}, []
    for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if linha.startswith("#"):
            chave, _, valor = linha.lstrip("# ").partition(":")
            metadados[chave.strip().lower()] = valor.strip()
        elif linha:
            mensagens.append(linha)
    return metadados, mensagens


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

    metadados, roteiro = ler_roteiro(args.roteiro) if args.roteiro else ({}, [])
    if metadados.get("data_referencia"):
        os.environ["DATA_REFERENCIA"] = metadados["data_referencia"]

    # No modo debug (e no modo roteiro), cada tool chamada e cada nova tentativa aparece na hora.
    mostrar_eventos = args.debug or args.roteiro
    agente = AgenteEmporio(ao_evento=(lambda e: print(f"  🔧 {e}", flush=True)) if mostrar_eventos else None)

    if args.roteiro:
        def ecoar():
            for mensagem in roteiro:
                print(f"Você: {mensagem}")
                yield mensagem
        transcricao = Transcricao(
            agente.modelo,
            arquivo=PASTA_EXEMPLOS / f"{args.roteiro.stem}.md",
            titulo=metadados.get("titulo", args.roteiro.stem),
        )
        if conversar(agente, ecoar(), transcricao):
            print("⚠️  Alguma resposta falhou por erro da API. Rode o roteiro de novo mais tarde.")
    else:
        print("Lia, da Empório da Música 🎸  (digite /nova para recomeçar ou /sair para encerrar)\n")
        conversar(agente, mensagens_interativas(), Transcricao(agente.modelo))


if __name__ == "__main__":
    main()
