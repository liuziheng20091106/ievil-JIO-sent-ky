"""虚拟玩家模拟器：用真实协议驱动一整局，用于测试游戏规则与阶段推进。

模拟器不直接调用规则层，而是和其它客户端一样走 HTTP/WebSocket：
真实登录、真实命令、真实 expected_version、真实服务端可见性裁剪都被覆盖。
"""

from .client import ProtocolClient, ProtocolError
from .driver import Roster, Simulation, SimulationResult, run_simulation
from .policy import HeuristicPolicy

__all__ = [
    "HeuristicPolicy",
    "ProtocolClient",
    "ProtocolError",
    "Roster",
    "Simulation",
    "SimulationResult",
    "run_simulation",
]
