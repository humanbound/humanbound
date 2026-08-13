import chromadb
from crewai import Agent, Crew
from langchain.memory import ConversationBufferMemory
from langchain_core.tools import tool
from openai import OpenAI

memory = ConversationBufferMemory()
db = chromadb.PersistentClient()


@tool
def search(q: str) -> str:
    return "ok"


def call_reasoning():
    OpenAI().chat.completions.create(model="o1-preview", messages=[], reasoning_effort="high")


crew = Crew(agents=[Agent(role="a", goal="b", backstory="c")])
