---
status: accepted
---

# Self-host the LangGraph runtime

Agent Hub will run LangGraph and Deep Agents in its own Python backend deployment rather than depend on a managed LangSmith deployment. The backend will be shipped as a Docker image and placed behind the platform's Nginx ingress, preserving control of deployment and the intended path to Azure. This decision does not select LangChain's separately licensed standalone Agent Server product; the frontend transport is recorded independently.
