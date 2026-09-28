# Marks "core" as a Python package.
# Core = database, AI service, language detection.
# Keeping these separate from app.py is what makes future
# modules (RAG, Notes, Tasks, Dashboard) easy to bolt on.
#
# Deploy note: nothing in this package imports torch / faiss /
# sentence-transformers, so importing it is cheap on serverless hosts.
