"""Carga e tratamento dos dados operacionais da loja (CSVs em data/)."""

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Baixos, baterias e teclados têm descrições que citam outra marca/modelo
# (ex.: "Music Man Bass 1X" descrito como "Fender Jazz Bass"). Nessas categorias
# a descrição é descartada e o agente usa apenas nome + specs.
CATEGORIAS_DESCRICAO_INCONSISTENTE = {2, 3, 4}


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para buscas tolerantes ("violao" encontra "Violão")."""
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower().strip()


def _ler(nome: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / f"{nome}.csv", encoding="utf-8")


def _promocoes_ativas() -> pd.DataFrame:
    promos = _ler("promotions")
    promos = promos[promos["is_active"] == 1]
    # Regra defensiva: se um produto tiver mais de uma promoção ativa, vale a de maior desconto
    # (o manual diz que promoções não são cumulativas).
    promos = promos.sort_values("discount_percent", ascending=False).drop_duplicates("product_id")
    return promos.rename(columns={"discount_percent": "desconto_pct", "description": "nome_promocao"})[
        ["product_id", "desconto_pct", "nome_promocao"]
    ]


@lru_cache(maxsize=1)
def carregar_produtos() -> pd.DataFrame:
    produtos = _ler("products")
    categorias = _ler("categories").rename(columns={"name": "categoria", "description": "descricao_categoria"})

    produtos = produtos.merge(categorias, on="category_id", how="left")
    produtos["specs"] = produtos["specs"].apply(json.loads)
    produtos["nome_busca"] = produtos["name"].map(normalizar)
    produtos["descricao"] = produtos["description"].where(
        ~produtos["category_id"].isin(CATEGORIAS_DESCRICAO_INCONSISTENTE)
    )

    # Disponível para venda = ativo no catálogo E com estoque.
    # Descontinuados e "em breve" são mantidos para o agente conseguir explicar a situação ao cliente.
    produtos["disponivel"] = (produtos["status"] == "active") & (produtos["stock_quantity"] > 0)

    produtos = produtos.merge(_promocoes_ativas(), on="product_id", how="left")
    produtos["desconto_pct"] = produtos["desconto_pct"].fillna(0)
    produtos["preco_final"] = (produtos["price_brl"] * (1 - produtos["desconto_pct"] / 100)).round(2)

    return produtos.sort_values("product_id").reset_index(drop=True)


@lru_cache(maxsize=1)
def carregar_pedidos() -> pd.DataFrame:
    pedidos = _ler("orders")
    for coluna in ("order_date", "estimated_delivery"):
        pedidos[coluna] = pd.to_datetime(pedidos[coluna])

    itens = _ler("order_items").merge(
        carregar_produtos()[["product_id", "name", "price_brl"]], on="product_id", how="left"
    )
    itens["subtotal"] = itens["quantity"] * itens["price_brl"]

    resumo = itens.groupby("order_id").apply(
        lambda g: pd.Series({
            "itens": [
                {"produto": r.name, "quantidade": int(r.quantity), "preco_unitario": float(r.price_brl)}
                for r in g.itertuples()
            ],
            "soma_itens": round(g["subtotal"].sum(), 2),
        }),
        include_groups=False,
    ).reset_index()
    pedidos = pedidos.merge(resumo, on="order_id", how="left")

    # Divergência entre o total registrado e a soma dos itens (ex.: descontos não documentados).
    # O agente informa o total registrado, mas sabemos onde os dados são inconsistentes.
    pedidos["total_confere"] = (pedidos["total_brl"] - pedidos["soma_itens"]).abs() < 0.01

    clientes = _ler("customers").rename(
        columns={"name": "cliente_nome", "email": "cliente_email", "phone": "cliente_telefone", "city": "cliente_cidade"}
    )
    return pedidos.merge(clientes, on="customer_id", how="left")


if __name__ == "__main__":
    produtos = carregar_produtos()
    pedidos = carregar_pedidos()
    print("Produtos:", len(produtos))
    print("Disponíveis para venda:", int(produtos["disponivel"].sum()))
    print("Com promoção ativa:", int(produtos["desconto_pct"].gt(0).sum()))
    print("Pedidos:", len(pedidos))
    print("Pedidos com total divergente:", pedidos.loc[~pedidos["total_confere"], "order_id"].tolist())
