"""Interface web (Streamlit) do agente de atendimento da Empório da Música.

Uso:
    streamlit run app.py
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.agent import AgenteEmporio

ESTILO = Path(__file__).resolve().parent / "assets" / "estilo.css"
AVATAR_LIA = "🎸"
AVATAR_CLIENTE = "🙂"
BOAS_VINDAS = (
    "Oi! Eu sou a **Lia**, assistente virtual da Empório da Música. 🎶\n\n"
    "Posso te ajudar a encontrar instrumentos, consultar preços e promoções, "
    "acompanhar pedidos e tirar dúvidas sobre pagamento, trocas e entregas. Como posso ajudar?"
)
# Cartões da tela inicial: (rótulo do cartão, pergunta enviada à Lia).
ATALHOS = [
    ("🎸  **Violões até R\\$ 1.000**  \nOpções disponíveis para começar", "Quais violões vocês têm disponíveis até R$ 1000?"),
    ("💰  **Preço e pagamento**  \nQuanto custa o Takamine GD20?", "Quanto custa o Takamine GD20? Dá pra parcelar?"),
    ("📦  **Meu pedido**  \nStatus, rastreio e entrega", "Quero saber o status do meu pedido."),
    ("🔁  **Trocas e devoluções**  \nComo funciona o arrependimento", "Me arrependi da compra, posso devolver meu pedido?"),
]
EXEMPLOS = [
    "Quais violões vocês têm disponíveis até R$ 1000?",
    "Quanto custa o Takamine GD20?",
    "Qual o endereço e o horário da loja?",
    "Me arrependi da compra, posso devolver meu pedido?",
    "Vocês vendem cordas para guitarra?",
]


def escapar(texto: str) -> str:
    # O Markdown do Streamlit interpreta "$...$" como fórmula; "R$ 10 ... R$ 20" quebraria a formatação.
    return texto.replace("$", "\\$")


def mostrar(mensagem: dict, indice: int) -> None:
    da_lia = mensagem["papel"] == "assistant"
    # A key do container vira uma classe CSS (st-key-...), usada para estilizar cada tipo de balão.
    with st.container(key=f"msg-{'lia' if da_lia else 'cliente'}-{indice}"):
        with st.chat_message(mensagem["papel"], avatar=AVATAR_LIA if da_lia else AVATAR_CLIENTE):
            st.markdown(escapar(mensagem["texto"]))
            ferramentas = mensagem.get("ferramentas")
            if ferramentas:
                with st.expander(f"🔧 Consultas feitas ({len(ferramentas)})"):
                    for chamada in ferramentas:
                        st.code(chamada, language=None)


def iniciar_sessao() -> None:
    st.session_state.agente = AgenteEmporio()
    st.session_state.mensagens = []


st.set_page_config(page_title="Lia · Empório da Música", page_icon=AVATAR_LIA)
st.markdown(f"<style>{ESTILO.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
load_dotenv()

if not os.getenv("GEMINI_API_KEY"):
    st.error(
        "Chave da Gemini API não encontrada. Crie o arquivo `.env` a partir do `.env.example` "
        "e preencha `GEMINI_API_KEY` (veja o README)."
    )
    st.stop()

# O Streamlit reexecuta este script a cada interação: o agente (com o histórico da conversa)
# fica guardado na sessão do navegador.
if "agente" not in st.session_state:
    iniciar_sessao()
agente: AgenteEmporio = st.session_state.agente

pergunta_exemplo = None
with st.sidebar:
    st.header("🎸 Empório da Música")
    if st.button("🔄 Nova conversa", key="nova-conversa", width="stretch"):
        agente.nova_conversa()
        st.session_state.mensagens = []
        st.rerun()

    st.subheader("Experimente perguntar")
    for indice, exemplo in enumerate(EXEMPLOS):
        if st.button(exemplo, key=f"exemplo_{indice}", width="stretch"):
            pergunta_exemplo = exemplo

    st.divider()
    # Preenchido no fim do script, depois da resposta, para refletir uma eventual troca de modelo.
    indicador_modelo = st.empty()

st.markdown(
    """
    <div class="em-cabecalho">
      <div class="em-marca">EMPÓRIO DA <span>MÚSICA</span></div>
      <div class="em-slogan">Sua música começa aqui.</div>
      <div class="em-lia"><span class="em-eq"><i></i><i></i><i></i><i></i></span>Lia está online para te atender</div>
    </div>
    """,
    unsafe_allow_html=True,
)

mostrar({"papel": "assistant", "texto": BOAS_VINDAS}, indice=-1)
mostrou_atalhos = not st.session_state.mensagens
if mostrou_atalhos:
    st.markdown('<div class="em-titulo-atalhos">Por onde quer começar?</div>', unsafe_allow_html=True)
    colunas = st.columns(2)
    for indice, (rotulo, pergunta_atalho) in enumerate(ATALHOS):
        with colunas[indice % 2]:
            if st.button(rotulo, key=f"atalho-{indice}", width="stretch"):
                pergunta_exemplo = pergunta_atalho
for indice, mensagem in enumerate(st.session_state.mensagens):
    mostrar(mensagem, indice)

pergunta = st.chat_input("Escreva sua dúvida para a Lia…", height=72, submit_mode="disable") or pergunta_exemplo
if pergunta:
    mensagem_cliente = {"papel": "user", "texto": pergunta}
    st.session_state.mensagens.append(mensagem_cliente)
    mostrar(mensagem_cliente, len(st.session_state.mensagens) - 1)

    with st.spinner("Lia está digitando..."):
        resposta = agente.responder(pergunta)
    mensagem_lia = {"papel": "assistant", "texto": resposta.texto, "ferramentas": resposta.ferramentas}
    st.session_state.mensagens.append(mensagem_lia)
    mostrar(mensagem_lia, len(st.session_state.mensagens) - 1)
    if mostrou_atalhos:
        st.rerun()  # redesenha a tela sem os cartões de atalho, que só aparecem antes da 1ª pergunta

indicador_modelo.markdown(
    f'<div class="em-rodape-lateral">Respostas baseadas no catálogo e no manual da loja.<br>'
    f"Modelo em uso: <code>{agente.modelo}</code></div>",
    unsafe_allow_html=True,
)
