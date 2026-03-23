import sys
from abc import abstractmethod, ABC

import requests

sys.path.insert(0, "../../src")
# All imports at the top
from vanna import Agent, AgentConfig
from vanna.core.registry import ToolRegistry
from vanna.core.user import UserResolver, User, RequestContext
from vanna.tools import RunSqlTool, VisualizeDataTool
from vanna.tools.agent_memory import SaveQuestionToolArgsTool, SearchSavedCorrectToolUsesTool, SaveTextMemoryTool
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.integrations.ollama import OllamaLlmService
from vanna.integrations.mysql import MySQLRunner
from vanna.integrations.chromadb import ChromaAgentMemory
from vanna.core.system_prompt import SystemPromptBuilder
from vanna.core import LlmContextEnhancer
from vanna import LlmMessage
from typing import List, Dict, Any

# Configure your LLM
llm = OllamaLlmService(
    # model="qwen3-coder-next:latest",
    model="qwen3.5:35b",
    host="http://10.113.53.161:11434"
)

# Configure your database
db_tool = RunSqlTool(
    sql_runner=MySQLRunner(
        host="10.113.53.163",
        database="gzzybppj",
        user="bppj_all",
        password="xiaolang",
        port=3306
    )
)

# Configure your agent memory
agent_memory = ChromaAgentMemory(
    collection_name="vanna_memory",
    persist_directory="./chroma_db"
)


# Configure user authentication
class SimpleUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        user_email = request_context.get_cookie('vanna_email') or 'guest@example.com'
        group = 'admin' if user_email == 'admin@example.com' else 'user'
        return User(id=user_email, email=user_email, group_memberships=[group])


user_resolver = SimpleUserResolver()

# Create your agent
tools = ToolRegistry()
tools.register_local_tool(db_tool, access_groups=['admin', 'user'])
tools.register_local_tool(SaveQuestionToolArgsTool(), access_groups=['admin'])
tools.register_local_tool(SearchSavedCorrectToolUsesTool(), access_groups=['admin', 'user'])
tools.register_local_tool(SaveTextMemoryTool(), access_groups=['admin', 'user'])
tools.register_local_tool(VisualizeDataTool(), access_groups=['admin', 'user'])

agentConfig = AgentConfig()
agentConfig.max_tool_iterations = 20


class OktaUserResolver(UserResolver):

    async def resolve_user(self, request_context: RequestContext) -> User:
        auth_header = request_context.get_header('Authorization')

        if not auth_header or not auth_header.startswith('Bearer '):
            return User(id="anonymous", username="guest")

        token = auth_header.split(' ')[1]

        try:
            headers = {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json"
            }
            response = requests.get("http://10.113.53.161:23313/system/user/getInfo", headers=headers)
            userinfo = response.json()['user']
            parent_dept = response.json()['parentDept']

            # Extract user information from Okta claims
            return User(
                id=userinfo['userName'],
                username=userinfo['nickName'],
                email=userinfo['email'],
                group_memberships=['user'],
                metadata={
                    'parentDept': parent_dept,
                }
            )
        except Exception as e:
            print(e)
            # Token validation failed
            return User(id="anonymous", username="guest")


class DocumentationEnhancer(LlmContextEnhancer):

    async def enhance_system_prompt(
            self,
            system_prompt: str,
            user_message: str,
            user: User
    ) -> str:
        # Search documentation based on user question
        print(system_prompt)
        return system_prompt + " 使用中文回答所有问题"

    async def enhance_user_messages(
            self,
            messages: list[LlmMessage],
            user: User
    ) -> list[LlmMessage]:
        if (user.metadata.get('parentDept')['deptName'] != '贵州中烟工业有限责任公司'):
            docs_section = "  仅查询单位名称是" + user.metadata.get('parentDept')['deptName'] + "的数据"
            for msg in messages:
                if msg.role == "user" and msg.content:
                    msg.content += docs_section
        return messages


agent = Agent(
    config=agentConfig,
    llm_service=llm,
    tool_registry=tools,
    user_resolver=OktaUserResolver(),
    agent_memory=agent_memory,
    llm_context_enhancer=DocumentationEnhancer()
)

# Run the server
server = VannaFastAPIServer(agent)
server.run()  # Access at http://localhost:8000
