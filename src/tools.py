"""Ferramentas (function calling) que o agente usa para consultar os dados da loja.

Regra geral: todo cálculo (preço com desconto, prazos de troca, atraso de entrega)
é feito aqui em Python. O LLM só recebe o resultado pronto e redige a resposta.
"""

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from src.data_loader import carregar_pedidos, carregar_produtos, normalizar

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
MAX_RESULTADOS = 15
PALAVRAS_IGNORADAS = {"de", "da", "do", "das", "dos", "com", "para", "e", "a", "o", "um", "uma", "em"}

# Palavras que o cliente usa para cada categoria (singular, plural, sinônimos).
# Inclui categorias sem produtos (6, 7, 8) para a busca retornar "nenhum resultado"
# em vez de trazer itens de outra categoria.
SINONIMOS_CATEGORIA = {
    1: "guitarra guitarras",
    2: "baixo baixos contrabaixo contrabaixos",
    3: "bateria baterias percussao",
    4: "teclado teclados piano pianos sintetizador sintetizadores",
    5: "violao violoes",
    6: "sopro madeira flauta clarinete saxofone sax oboe",
    7: "sopro metal metais trompete trombone tuba trompa",
    8: "violino violinos viola violoncelo cello orquestral",
    9: "ukulele ukuleles",
}

STATUS_PEDIDO = {
    "pending": "Pendente (aguardando confirmação do pagamento)",
    "confirmed": "Confirmado (pagamento aprovado, em separação)",
    "shipped": "Enviado (em transporte)",
    "delivered": "Entregue",
    "cancelled": "Cancelado",
}


def data_referencia() -> date:
    """Data usada como "hoje". Configurável via DATA_REFERENCIA (AAAA-MM-DD) para simular cenários."""
    valor = os.getenv("DATA_REFERENCIA")
    return date.fromisoformat(valor) if valor else date.today()


def _data_br(valor) -> str | None:
    return None if pd.isna(valor) else valor.strftime("%d/%m/%Y")


def _forma_pagamento(codigo: str) -> str:
    if codigo.startswith("credit_"):
        return f"Cartão de crédito em {codigo.removeprefix('credit_')}"
    return {"pix": "PIX", "debit": "Cartão de débito", "boleto": "Boleto bancário"}.get(codigo, codigo)


def _situacao(produto) -> str:
    if produto["status"] == "discontinued":
        return "Fora de linha (não faz mais parte do catálogo)"
    if produto["status"] == "coming_soon":
        return "Em breve (ainda não disponível para venda)"
    if produto["stock_quantity"] <= 0:
        return "Temporariamente sem estoque"
    if produto["stock_quantity"] <= 2:
        return "Disponível (últimas unidades)"
    return "Disponível"


def _parcelamento_maximo(preco: float) -> dict:
    """Maior número de parcelas sem juros respeitando a parcela mínima do manual (seção 3.1).

    Suposição: "até 3x sem valor mínimo (exceto abaixo de R$ 50)" = parcela mínima de R$ 50 até 3x.
    """
    for vezes in range(12, 0, -1):
        minimo = 100 if vezes >= 7 else 80 if vezes >= 4 else 50
        if preco / vezes >= minimo or vezes == 1:
            return {"vezes": vezes, "valor_parcela": round(preco / vezes, 2)}


def _resumo_produto(produto) -> dict:
    preco_final = float(produto["preco_final"])
    resumo = {
        "produto_id": int(produto["product_id"]),
        "nome": produto["name"],
        "categoria": produto["categoria"],
        "preco_final": preco_final,
        "situacao": _situacao(produto),
        "parcelamento_maximo_sem_juros": _parcelamento_maximo(preco_final),
    }
    if produto["desconto_pct"] > 0:
        resumo["preco_original"] = float(produto["price_brl"])
        resumo["desconto_pct"] = int(produto["desconto_pct"])
        resumo["promocao"] = produto["nome_promocao"]
        resumo["preco_pix"] = "Desconto de 5% no PIX não se aplica: promoções não são cumulativas."
    else:
        resumo["preco_pix"] = round(preco_final * 0.95, 2)
    return resumo


def _texto_busca(produto) -> str:
    specs = " ".join(str(v) for v in produto["specs"].values())
    return " ".join([
        produto["nome_busca"],
        normalizar(produto["categoria"]),
        SINONIMOS_CATEGORIA.get(produto["category_id"], ""),
        normalizar(specs),
    ])


def buscar_produtos(
    termo: str = "",
    categoria: str = "",
    preco_maximo: float = 0,
    somente_disponiveis: bool = False,
) -> dict:
    """Busca instrumentos no catálogo da loja. Use para perguntas sobre preço, disponibilidade ou opções de produtos.

    Args:
        termo: Palavras do nome, marca ou característica (ex.: "takamine gd20", "nylon", "eletrico"). Vazio = sem filtro.
        categoria: Tipo de instrumento (ex.: "violão", "guitarra", "baixo", "bateria", "teclado", "ukulele", "flauta"). Vazio = todas.
        preco_maximo: Preço máximo em reais, já considerando promoções. 0 = sem limite.
        somente_disponiveis: True para trazer apenas itens à venda e com estoque.

    Returns:
        Produtos encontrados (até 15, do mais barato ao mais caro) com preço final, promoção e situação de estoque.
    """
    produtos = carregar_produtos()
    filtro = pd.Series(True, index=produtos.index)

    if categoria:
        palavras_categoria = normalizar(categoria).split()
        ids = [cid for cid, sin in SINONIMOS_CATEGORIA.items() if any(p in sin.split() for p in palavras_categoria)]
        filtro &= produtos["category_id"].isin(ids)

    if termo:
        textos = produtos.apply(_texto_busca, axis=1)
        for palavra in normalizar(termo).split():
            if palavra not in PALAVRAS_IGNORADAS:
                filtro &= textos.str.contains(palavra, regex=False)

    if preco_maximo > 0:
        filtro &= produtos["preco_final"] <= preco_maximo
    if somente_disponiveis:
        filtro &= produtos["disponivel"]

    encontrados = produtos[filtro].sort_values("preco_final")
    resultado = {
        "total_encontrado": len(encontrados),
        "produtos": [_resumo_produto(p) for _, p in encontrados.head(MAX_RESULTADOS).iterrows()],
    }
    if len(encontrados) > MAX_RESULTADOS:
        resultado["observacao"] = f"Mostrando os {MAX_RESULTADOS} mais baratos de {len(encontrados)}. Refine a busca para ver outros."
    if encontrados.empty:
        resultado["observacao"] = "Nenhum produto encontrado com esses critérios no catálogo atual."
    return resultado


def detalhes_produto(produto_id: int) -> dict:
    """Retorna a ficha completa de um produto (especificações técnicas e descrição).

    Args:
        produto_id: Identificador do produto, obtido em buscar_produtos.
    """
    produtos = carregar_produtos()
    linha = produtos[produtos["product_id"] == produto_id]
    if linha.empty:
        return {"erro": f"Produto {produto_id} não encontrado."}
    produto = linha.iloc[0]
    detalhes = _resumo_produto(produto)
    detalhes["especificacoes"] = produto["specs"]
    if pd.notna(produto["descricao"]):
        detalhes["descricao"] = produto["descricao"]
    return detalhes


def _identidade_confere(pedido, email_ou_telefone: str) -> bool:
    informado = email_ou_telefone.strip().lower()
    if "@" in informado:
        return informado == str(pedido["cliente_email"]).lower()
    digitos = re.sub(r"\D", "", informado)
    return len(digitos) >= 8 and re.sub(r"\D", "", str(pedido["cliente_telefone"])).endswith(digitos)


def _prazos(pedido, hoje: date) -> dict:
    """Prazos do manual (seções 4 e 8), calculados para pedidos entregues.

    Suposição: o CSV não tem a data real de recebimento, então usamos a previsão de entrega.
    """
    recebimento = pedido["estimated_delivery"].date()
    compra = pedido["order_date"].date()
    limites = {
        "arrependimento_7_dias_apos_recebimento": recebimento + timedelta(days=7),
        "troca_por_preferencia_7_dias": recebimento + timedelta(days=7),
        "troca_por_defeito_30_dias_apos_compra": compra + timedelta(days=30),
        "garantia_legal_90_dias_apos_recebimento": recebimento + timedelta(days=90),
    }
    return {
        nome: {"ate": limite.strftime("%d/%m/%Y"), "dentro_do_prazo": hoje <= limite}
        for nome, limite in limites.items()
    }


def consultar_pedido(numero_pedido: int, email_ou_telefone: str) -> dict:
    """Consulta status, itens, rastreio e prazos de troca de um pedido. Exige verificação de identidade.

    Args:
        numero_pedido: Número do pedido informado pelo cliente.
        email_ou_telefone: E-mail ou telefone cadastrado do cliente, para confirmar que o pedido é dele.
    """
    pedidos = carregar_pedidos()
    linha = pedidos[pedidos["order_id"] == numero_pedido]
    # Mesma mensagem para "pedido não existe" e "dados não conferem": não revela quais pedidos existem (LGPD).
    if linha.empty or not _identidade_confere(linha.iloc[0], email_ou_telefone):
        return {"erro": "Não foi possível localizar o pedido com esses dados. Peça ao cliente para conferir o número do pedido e o e-mail ou telefone cadastrado."}

    pedido = linha.iloc[0]
    hoje = data_referencia()
    resultado = {
        "numero_pedido": int(pedido["order_id"]),
        "cliente": pedido["cliente_nome"],
        "data_pedido": _data_br(pedido["order_date"]),
        "status": STATUS_PEDIDO.get(pedido["status"], pedido["status"]),
        "itens": pedido["itens"],
        "total": float(pedido["total_brl"]),
        "forma_pagamento": _forma_pagamento(pedido["payment_method"]),
        "data_de_hoje": hoje.strftime("%d/%m/%Y"),
    }
    if pd.notna(pedido["tracking_code"]):
        resultado["codigo_rastreio"] = pedido["tracking_code"]
    if pd.notna(pedido["estimated_delivery"]):
        resultado["previsao_entrega"] = _data_br(pedido["estimated_delivery"])
    if pd.notna(pedido["notes"]):
        resultado["observacao"] = pedido["notes"]

    if pedido["status"] == "shipped" and pedido["estimated_delivery"].date() < hoje:
        resultado["entrega_atrasada"] = True
    if pedido["status"] == "delivered":
        resultado["prazos"] = _prazos(pedido, hoje)
    if not pedido["total_confere"]:
        resultado["aviso_interno"] = "O total registrado difere da soma dos itens. Se o cliente questionar valores, encaminhe para a equipe em vez de explicar a diferença."
    return resultado


def listar_promocoes() -> dict:
    """Lista as promoções ativas no momento, com preço original, desconto e preço final."""
    produtos = carregar_produtos()
    em_promocao = produtos[(produtos["desconto_pct"] > 0) & (produtos["status"] == "active")]
    return {"promocoes_ativas": [_resumo_produto(p) for _, p in em_promocao.sort_values("preco_final").iterrows()]}


def registrar_reclamacao(nome_cliente: str, contato: str, descricao: str, numero_pedido: int = 0) -> dict:
    """Registra uma reclamação para a equipe humana tratar (retorno em até 24 horas úteis).

    Args:
        nome_cliente: Nome do cliente.
        contato: Telefone ou e-mail para retorno.
        descricao: Resumo do problema relatado.
        numero_pedido: Número do pedido relacionado, se houver (0 = nenhum).
    """
    LOG_DIR.mkdir(exist_ok=True)
    protocolo = "REC-" + datetime.now().strftime("%Y%m%d%H%M%S")
    registro = {
        "protocolo": protocolo,
        "registrado_em": datetime.now().isoformat(timespec="seconds"),
        "nome_cliente": nome_cliente,
        "contato": contato,
        "numero_pedido": numero_pedido or None,
        "descricao": descricao,
    }
    with open(LOG_DIR / "reclamacoes.jsonl", "a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return {"protocolo": protocolo, "prazo_retorno": "até 24 horas úteis"}


FERRAMENTAS = [buscar_produtos, detalhes_produto, consultar_pedido, listar_promocoes, registrar_reclamacao]
