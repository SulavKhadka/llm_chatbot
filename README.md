Intro
---
Using this as a practice for making agents and deploying them on discord as testing grounds.

Right now the backend is a vllm openai inference server. SGlang has been tested but they dont have tool support yet so sticking with vllm


Notes
---
- I see that for time and time conversions its not able to calculate given that it has the correct time given to it at all times. Need some fn calling implementations.
- It has a very reddit flavored speech antics. system prompt might need tweaking, need to instruct to be authentic and not a yes man always while still being helpful
- How can I get it to remember its system prompt but not talk about it too much or in conversations
- need instruction to not hallucinate any tools, and be transparent to user if its not able to accomplish the task
- add a tool maker, where its able to generate tools (thats a little out of scope bc of its complixity for now)
- need to add examples of when to use <self_response>, <user_response>, and <plan>
- what to do with <thoughts>, its helpful for it to analyze before outputting a response but after do we just discard?
- some <self_response> might just be a little note the LLM is keeping for itself, this should be allowed and handled. maybe we need to show examples of this for it to behave correctly here.
- omitting tags out of the messages list is bad because it starts following how previous messages of the convo, which if we remove the tags we include in the guideline it will confuse it. hmmmm what to do?
- i think im only logging successful fn/tool calls. need to inspect logging a bit closer.
- multi tool call works and chained tool calling seems to work as well. need to do an eval on this

thoughts on tools
---
- How to enable using a large set of tools?
- tool chaining and mixing by including tools and their code as rag inputs and have the llm craft a function that uses the tools and execute it in the python interpreter to achieve its goal
- browser access and web browsing capable tool/agent is needed maybe even necessary. maybe use open-interpreter and slowly build my own?
- how to give access to personals (gmail, messages, social_media) for monitoring as a personal assistant
- need to use the screenshot tool and chain it with VLMs to have it understand what the user is seeing
- how to enable uploading of files to discuss about and feed it into the LLM.

active learning
---
- how can the agent learn from interacting(chatting/tool use) with its environment?
- RAG storage is probably the only way for now. other wayt involves thinking about active training and synthetic data generation so that seems too complicated for now.

misc
---
- vllm openAI endpoints
    - `/openapi.json`, Methods: GET, HEAD
    - `/docs`, Methods: GET, HEAD
    - `/docs/oauth2-redirect`, Methods: GET, HEAD
    - `/redoc`, Methods: GET, HEAD
    - `/health`, Methods: GET
    - `/tokenize`, Methods: POST
    - `/detokenize`, Methods: POST
    - `/v1/models`, Methods: GET
    - `/version`, Methods: GET
    - `/v1/chat/completions`, Methods: POST
    - `/v1/completions`, Methods: POST
    - `/v1/embeddings`, Methods: POST

clean install
---
```bash
\# install uv
apt update
apt install -y postgresql
apt install -y poppler-utils libpq-dev python3.11-dev

curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
uv python install 3.11

git clone https://github.com/SulavKhadka/llm_chatbot.git
cd llm_chatbot

uv venv --python=3.12
source .venv/bin/activate

uv pip install python-telegram-bot discord.py transformers pydantic openai loguru logfire llama-index geopy huggingface-hub mss langchain ipykernel ipywidgets nvitop torchvision pdf2image qwen-vl-utils torch psutil psycopg2 psycopg2-binary langchain-community "wikibase-rest-api-client<0.2" mediawikiapi arxiv

uv pip install -U pip
python -m pip install flash-attn --no-build-isolation


\# To add $HOME/.cargo/bin to your PATH
```

To-Do
---
[x] Add to system prompt some realtime details to give the chatbot some grounding and info: DateTime
