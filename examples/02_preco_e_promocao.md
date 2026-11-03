# Preço, promoção e regra de não cumulatividade

_Modelo principal: gemini-3.5-flash | Gerado em 03/11/2026 12:07_

> 🔧 indica as ferramentas que o agente chamou para responder.

**Cliente:** Quanto custa o Takamine GD20?

> 🔧 `buscar_produtos(termo='Takamine GD20')`  
> 🔧 `[gemini-3.5-flash: cota diária esgotada]`  
> 🔧 `[trocando para o modelo gemini-3.5-flash-lite]`

**Lia:** O Takamine GD20 Dreadnought Natural custa R$ 2.199,00 à prazo (ou R$ 2.089,05 no PIX), e você pode parcelar em até 12x de R$ 183,25 sem juros! 🎸

Ele está disponível aqui na loja. Quer saber mais detalhes sobre ele?

**Cliente:** E o ukulele Ohana CK-20? Se eu pagar no PIX ganho mais desconto?

> 🔧 `buscar_produtos(termo='Ohana CK-20')`  
> 🔧 `consultar_politica(topico='formas_de_pagamento')`

**Lia:** O ukulele Ohana CK-20 Concert Natural está em promoção por R$ 439,20 (preço original de R$ 549,00, com 20% de desconto). 

Como ele já está em promoção, o desconto de 5% do PIX não é acumulativo, beleza? Mas você ainda pode levar ele parcelado em até 5x de R$ 87,84 sem juros se preferir! 🎶

**Cliente:** Vocês têm o Giannini GF-3D?

> 🔧 `[API 504 no gemini-3.5-flash-lite, nova tentativa em 2s]`  
> 🔧 `buscar_produtos(termo='Giannini GF-3D')`

**Lia:** O violão Giannini GF-3D Dreadnought Sunburst custa R$ 799,90 (ou R$ 759,90 no PIX, com parcelamento em até 7x de R$ 114,27 sem juros), mas no momento ele está **temporariamente sem estoque**. 

Quer que eu te mostre outras opções parecidas que temos disponíveis por aqui? 🎸

---

_Modelos que geraram as respostas: gemini-3.5-flash, gemini-3.5-flash-lite_
