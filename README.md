# Chatbot Backend (FastAPI + Stripe + OpenAI)

Backend prêt à déployer sur Render :
- `/chat` : chat IA (OpenAI GPT-4o-mini)
- `/usage/{client_id}` : compteur mensuel (messages + tokens) selon plan
- `/billing/checkout?plan=basic|pro|illimite` : redirection vers tes Payment Links Stripe
- `/stripe/webhook` : met à jour automatiquement le **plan** après paiement

## 1) Déploiement Render (Web Service)
- **Build Command** : `pip install -r requirements.txt`
- **Start Command** : `uvicorn main:app --host 0.0.0.0 --port $PORT`
- (Optionnel) `runtime.txt` est fourni (Python 3.11.9)

## 2) Variables d'environnement à ajouter (Render → Environment)
- `OPENAI_API_KEY = sk-...`
- `STRIPE_SECRET_KEY = sk_test_...` (ou `sk_live_...` en prod)
- `STRIPE_WEBHOOK_SECRET = whsec_...` (créé dans Stripe → Developers → Webhooks)

## 3) Plans & quotas
- Basic : **1200** msgs/mois
- Pro : **5000** msgs/mois
- Illimité : sans limite

Le **client_id = e-mail**. Le webhook associe l'abonnement au bon e-mail (collecté par Stripe) et met à jour la base.

## 4) Tests rapides
- `GET /` → `{ "ok": true }`
- `POST /chat` avec JSON :
```json
{"client_id":"client@pme.fr","message":"Bonjour"}
```
- `GET /usage/client@pme.fr`

## 5) Notes Stripe (Payment Links)
- Les 3 Payment Links sont configurés dans `main.py` (`PAYMENT_LINKS`). Renomme tes produits Stripe en **Basic / Pro / Illimité** pour une détection fiable.
- Envoie au client un lien comme :
  `https://TON-BACKEND.onrender.com/billing/checkout?client_id=client@pme.fr&plan=pro`
  (la redirection va simplement ouvrir le Payment Link Pro)

## 6) Persistance
Ce starter utilise **SQLite** (fichier `db.sqlite`). Sur Render, le disque est éphémère à chaque redeploy. Pour garder l'historique, passe à **Render PostgreSQL** plus tard et adapte `usage.py`.
