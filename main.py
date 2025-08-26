# main.py
import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from openai import OpenAI
import stripe

# ====== CONFIG OPENAI ======
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY environment variable")
client = OpenAI(api_key=OPENAI_API_KEY)

# ====== STRIPE (payment links + webhook) ======
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")  # sk_test_... ou sk_live_...
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")  # whsec_...
if not STRIPE_SECRET_KEY:
    raise RuntimeError("Missing STRIPE_SECRET_KEY environment variable")
stripe.api_key = STRIPE_SECRET_KEY

# Tes liens Payment Links (Basic / Pro / Illimité) - déjà fournis
PAYMENT_LINKS = {
    "basic":   "https://buy.stripe.com/test_cNieV79Oe1cW010cZn8so03",
    "pro":     "https://buy.stripe.com/test_fZu8wJe4uaNw0103oN8so04",
    "illimite":"https://buy.stripe.com/test_7sY28lf8yg7Q7ts9Nb8so05",
}

# ====== USAGE / PLANS ======
from usage import (
    init_db, get_usage, log_usage,
    get_limit, get_plan, set_plan,
    set_stripe_customer_id, get_stripe_customer_id,
)
init_db()  # crée les tables si besoin

# ---------- Prompts (exemples) ----------
PROMPTS = {
    "innerskin": (
        "Tu es l’assistant officiel d’Innerskin, centre d’esthétique médicale non-invasive. "
        "Ton rôle : conseiller les clients avec expertise, bienveillance et un ton vendeur mais élégant. "
        "Réponds en 2 à 4 phrases maximum, toujours de manière claire et rassurante. "
        "Ne jamais inventer. Si une information n’est pas disponible, indique poliment qu’il faut prendre rendez-vous pour un devis personnalisé.\n\n"
        "SOINS PRINCIPAUX\n"
        "- Hydrafacial : nettoyage, exfoliation et hydratation en profondeur. "
        "Durée : à partir de 45 minutes. Prix : à partir de 180 €.\n"
        "- Peeling chimique : personnalisation selon le type de peau (imperfections, teint terne, ridules). "
        "Durée : environ 30 minutes. Prix : à partir de 150 €.\n"
        "- Épilation électrique (zones sensibles, duvet clair, poils résistants). "
        "15 min : 60 € (5 séances 250 €). 30 min : 100 € (5 séances 400 €). 45 min : 140 € (5 séances 600 €).\n\n"
        "DIFFÉRENCIATION : approche médicale, technologies non invasives, personnalisation, gamme cosmétique complémentaire, centres à Paris et grandes villes.\n\n"
        "RÈGLES DE CONSEIL :\n"
        "- Si le besoin est général : propose le soin le plus pertinent (ex. peau terne → Hydrafacial, imperfections → Peeling, poils clairs → Épilation électrique).\n"
        "- Si un prix exact est demandé : préciser que c’est “à partir de” et orienter vers un rendez-vous.\n"
        "- Toujours proposer une action concrète : prise de RDV, appel, découverte de la gamme cosmétique.\n"
    ),
    "la-stella-12e": (
        "Tu es l’assistant officiel de La Stella (pizzeria, Paris 12e). "
        "Tonalité: chaleureuse et concise. Objectif: aider à réserver/commander. "
        "Horaires: 11h30-14h30 et 18h30-22h30. Tel: 01 23 45 67 89. "
        "Offre: pizzas napolitaines, menu midi 14,90€, option sans gluten. "
        "Règles: Réponds en 3–5 phrases. Ne pas inventer; si info manquante, le dire."
    )
}

# ---------- FastAPI ----------
app = FastAPI(title="Chat Backend", version="1.0.0")

# CORS (ouvert pour tests — restreins en prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatIn(BaseModel):
    client_id: str  # -> email recommandé (ex: client@pme.fr)
    message: str
    session_id: str | None = None

@app.get("/")
def health():
    return {"ok": True}

# ====== ENDPOINTS BILLING ======

@app.get("/billing/checkout")
def billing_checkout(client_id: str, plan: str):
    """
    Redirige vers TON lien Payment Link selon le plan demandé.
    Note: Payment Links ne passent pas de metadata à Stripe.
    On s'appuie sur l'email collecté par Stripe et le produit acheté (via webhook).
    """
    url = PAYMENT_LINKS.get(plan)
    if not url:
        raise HTTPException(status_code=400, detail="Plan inconnu")
    return RedirectResponse(url, status_code=303)

@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Reçoit les événements Stripe et met à jour le plan du client en base.
    Compatible Payment Links : on lit l'email du payer et on infère le plan via le nom du produit.
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload, sig_header=sig, secret=STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Webhook verification failed: {e}"})

    etype = event.get("type", "")
    data = event["data"]["object"]

    # email côté session checkout
    email = None
    if "customer_details" in data and data["customer_details"]:
        email = data["customer_details"].get("email")

    customer_id = data.get("customer")
    plan = None

    # Déterminer le plan acheté (Payment Links)
    try:
        if etype == "checkout.session.completed":
            session = stripe.checkout.Session.retrieve(data["id"], expand=["line_items.data.price.product"])
            items = session["line_items"]["data"]
            if items:
                prod = items[0]["price"]["product"]
                pname = prod["name"].lower()
                if "illim" in pname:
                    plan = "illimite"
                elif "pro" in pname:
                    plan = "pro"
                elif "basic" in pname or "basique" in pname:
                    plan = "basic"
    except Exception:
        pass

    if etype in ("checkout.session.completed", "invoice.paid"):
        if email:
            if customer_id:
                set_stripe_customer_id(email, customer_id)
            if plan is None:
                plan = get_plan(email) or "basic"
            set_plan(email, plan)

    elif etype in ("customer.subscription.deleted",):
        if customer_id:
            try:
                cust = stripe.Customer.retrieve(customer_id)
                email = (cust.get("email") or (cust.get("metadata") or {}).get("client_id"))
            except Exception:
                email = None
        if email:
            set_plan(email, "basic")

    return {"ok": True}

# ====== USAGE/QUOTAS ======

@app.get("/usage/{client_id}")
def get_client_usage_endpoint(client_id: str):
    messages, tokens = get_usage(client_id)
    limit = get_limit(client_id)
    return {"client_id": client_id, "messages": messages, "tokens_used": tokens, "limit": limit}

@app.post("/chat")
def chat(inp: ChatIn):
    system_prompt = PROMPTS.get(inp.client_id, "Tu es un assistant utile et concis.")

    messages, tokens = get_usage(inp.client_id)
    limit = get_limit(inp.client_id)  # None => illimité
    if (limit is not None) and (messages >= limit):
        raise HTTPException(status_code=402, detail="Quota mensuel atteint pour votre offre.")

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": inp.message},
            ],
        )
        reply = completion.choices[0].message.content

        try:
            used_tokens = completion.usage.total_tokens if hasattr(completion, "usage") else 0
        except Exception:
            used_tokens = 0
        log_usage(inp.client_id, used_tokens)

        return {
            "reply": reply,
            "usage": {"messages": messages + 1, "tokens": tokens + used_tokens, "limit": limit}
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur OpenAI: {e}")
