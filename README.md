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

To-Do
---
[x] Add to system prompt some realtime details to give the chatbot some grounding and info: DateTime
