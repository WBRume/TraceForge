"""
Agent 状态同步协议解析器
解析 [AGENT_STATE_SYNC] ... [/AGENT_STATE_SYNC]
"""

import re
import json
from typing import Optional
from loguru import logger
from pydantic import BaseModel


class AgentStateSync(BaseModel):
    workspace_id: str
    task_id: str
    status: str
    sub_task: Optional[str] = None
    result: Optional[str] = None
    message: Optional[str] = None


class ProtocolParser:
    def __init__(self):
        # 跨行正则匹配 JSON 块
        self.pattern = re.compile(
            r"\[AGENT_STATE_SYNC\](.*?)\[/AGENT_STATE_SYNC\]", 
            re.DOTALL
        )
        self.buffer = ""

    def feed(self, output: str) -> list[AgentStateSync]:
        """
        传入增量输出流，返回提取到的状态标记
        并将被提取的标记从 buffer 中剔除，用于剥离显示
        """
        self.buffer += output
        found_states = []
        
        # 查找所有匹配
        matches = list(self.pattern.finditer(self.buffer))
        
        for match in matches:
            json_str = match.group(1).strip()
            try:
                data = json.loads(json_str)
                state = AgentStateSync(**data)
                found_states.append(state)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse AGENT_STATE_SYNC JSON: {e}")
            except Exception as e:
                logger.warning(f"Invalid AGENT_STATE_SYNC format: {e}")
                
        # 剥离匹配的内容
        if matches:
            # 取最后一个匹配的结束位置
            last_end = matches[-1].end()
            # 从 buffer 中移除匹配块...
            # 为简单起见，我们实际上在写入数据库或前端时应该替换掉这些标记
            # 这里的 buffer 维护供后续残缺 JSON 使用
            self.buffer = self.buffer[last_end:]
            
        return found_states

    def strip_tags(self, text: str) -> str:
        """从最终向前端展示的文本中剥除非用户友好的标签"""
        return self.pattern.sub("", text)
