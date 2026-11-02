"""Manual de políticas da loja: extração do PDF e consulta por seção.

O manual é curto (8 páginas) e já vem organizado em seções numeradas, então
usamos as seções como índice em vez de embeddings/RAG vetorial: a recuperação
é determinística e cada resposta pode ser rastreada até a seção do manual.
"""

import re
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

PDF_POLITICAS = Path(__file__).resolve().parent.parent / "data" / "politicas_da_loja.pdf"

# Número da seção no manual -> tópico usado pelo agente.
TOPICOS = {
    1: "sobre_a_loja",
    2: "horario_de_funcionamento",
    3: "formas_de_pagamento",
    4: "trocas_e_devolucoes",
    5: "frete_e_entregas",
    6: "promocoes_e_descontos",
    7: "diretrizes_de_atendimento",
    8: "garantia",
    9: "privacidade_e_dados",
    10: "disposicoes_finais",
}

# Inconsistências encontradas no manual e a interpretação adotada (documentadas no README).
NOTAS_DE_INTERPRETACAO = {
    "sobre_a_loja": (
        "O manual cita dois números: (67) 3341-4444 (capa e tabela de dados da empresa) e (67) 3321-4500 "
        "(seção de WhatsApp). Considere (67) 3341-4444 como telefone e WhatsApp oficiais, por aparecer nas "
        "fontes cadastrais. O e-mail correto é contato@emporiodamusica.com.br (sem acento). "
        "O catálogo atual do sistema prevalece sobre o texto institucional: se um tipo de instrumento não "
        "aparecer na busca de produtos, ele não está disponível."
    ),
    "diretrizes_de_atendimento": (
        "O WhatsApp oficial considerado é (67) 3341-4444 (ver nota em sobre_a_loja)."
    ),
    "formas_de_pagamento": (
        "A regra 'até 3x sem valor mínimo de parcela (exceto abaixo de R$ 50,00)' é interpretada como "
        "parcela mínima de R$ 50,00 no parcelamento em até 3x."
    ),
    "trocas_e_devolucoes": (
        "Os prazos de um pedido específico já vêm calculados pela ferramenta consultar_pedido; use-os "
        "em vez de calcular datas."
    ),
}


def _limpar(texto: str) -> str:
    linhas = []
    for linha in texto.splitlines():
        linha = linha.strip()
        # Cabeçalho e rodapé repetidos em todas as páginas.
        if not linha or linha.startswith("Empório da Música Manual de Políticas") or re.fullmatch(r"Página \d+", linha):
            continue
        # Colunas de tabela vêm separadas por vários espaços no modo layout.
        linhas.append(re.sub(r"\s{3,}", " | ", linha).replace("• | ", "• "))
    return "\n".join(linhas)


@lru_cache(maxsize=1)
def carregar_secoes() -> dict[str, str]:
    leitor = PdfReader(PDF_POLITICAS)
    texto = _limpar("\n".join(p.extract_text(extraction_mode="layout") for p in leitor.pages))

    # Títulos de seção de primeiro nível: "4. Política de Trocas e Devoluções" (não pega "4.1 ...").
    # Listas numeradas dentro das seções ("1. | Saudação...") são descartadas exigindo
    # que os títulos apareçam em sequência (1, 2, 3...) e sem separador de coluna.
    titulos = []
    for m in re.finditer(r"^(\d{1,2})\. (?!\|)", texto, flags=re.MULTILINE):
        if int(m.group(1)) == len(titulos) + 1:
            titulos.append(m)

    secoes = {}
    for i, m in enumerate(titulos):
        fim = titulos[i + 1].start() if i + 1 < len(titulos) else len(texto)
        secoes[TOPICOS[int(m.group(1))]] = texto[m.start():fim].strip()
    return secoes


def consultar_politica(topico: str) -> dict:
    """Consulta uma seção do manual oficial de políticas da loja. Use para dúvidas sobre regras e informações institucionais.

    Args:
        topico: Um dos tópicos: sobre_a_loja (endereço, contatos, o que a loja vende), horario_de_funcionamento,
            formas_de_pagamento (PIX, cartão, parcelamento), trocas_e_devolucoes (arrependimento, defeito, preferência),
            frete_e_entregas (prazos, valores, rastreio), promocoes_e_descontos (regras de promoções e cumulatividade),
            diretrizes_de_atendimento (escopo, reclamações, produto sem estoque ou descontinuado), garantia,
            privacidade_e_dados (LGPD), disposicoes_finais.
    """
    secoes = carregar_secoes()
    topico = topico.strip().lower()
    if topico not in secoes:
        return {"erro": f"Tópico '{topico}' não existe.", "topicos_validos": list(secoes)}

    resultado = {"topico": topico, "texto_do_manual": secoes[topico]}
    if topico in NOTAS_DE_INTERPRETACAO:
        resultado["nota_de_interpretacao"] = NOTAS_DE_INTERPRETACAO[topico]
    return resultado


if __name__ == "__main__":
    for nome, texto in carregar_secoes().items():
        print(f"===== {nome} ({len(texto)} caracteres)")
        print(texto[:300], "...\n")
