#!/usr/bin/env python3
# Copyright (c) 2025 李桥 (hubeiligang420@gmail.com)
# 专有软件 — 保留所有权利。禁止复制、修改、分发、逆向工程。
# Proprietary Software — ALL RIGHTS RESERVED.
#
"""
Anchor 事实检测器 — 独立 CLI 工具
输入 LLM 生成的文本，输出每条断言的可信度评估。

核心原理 (预测加工):
  先验强度 = 模型自信度 (logprobs / 流畅性)
  感官精度 = 外部事实核查结果
  幻觉 = 先验 >> 感官

用法:
  python3 hallucination_detector.py "朱元璋发明了火锅"
  python3 hallucination_detector.py --file output.txt
  python3 hallucination_detector.py --json "Python 是1991年发布的"
  cat response.txt | python3 hallucination_detector.py --stdin
"""

import argparse
import json
import re
import sys
from pathlib import Path
import time
from dataclasses import dataclass, field
from typing import Optional
import threading
from checker_registry import Checker
import checker_classes  # 触发 @checker 装饰器自动注册所有检查器

# 延迟导入嵌入检索引擎（避免循环依赖）
_embedding_searcher = None

def _get_embedding_searcher():
    global _embedding_searcher
    if _embedding_searcher is None:
        from embedding_search import EmbeddingSearcher
        _embedding_searcher = EmbeddingSearcher()
        _embedding_searcher.build_index(KNOWLEDGE_BASE)
    return _embedding_searcher

try:
    from logger import log
except ImportError:
    class _NoopLog:
        def __getattr__(self, _): return lambda *a, **k: None
    log = _NoopLog()
# ============================================================
# 知识库：可扩展的本地事实锚定
# ============================================================


# 同义词映射 — 增强语义匹配
SYNONYM_MAP = {
    "涮肉": "火锅", "涮锅": "火锅", "打边炉": "火锅",
    "明代开国皇帝": "朱元璋", "洪武皇帝": "朱元璋",
    "始皇": "秦", "始皇帝": "秦", "嬴政": "秦",
    "大唐": "唐", "李唐": "唐",
    "赵宋": "宋", "大宋": "宋",
    "朱明": "明", "大明": "明",
    "文景": "汉", "武帝": "汉",
    "雪峰": "珠穆朗玛峰", "珠峰": "珠穆朗玛峰",
    "红矮星": "太阳", "日": "太阳",
    "木卫": "木星",
    "红色星球": "火星",
    "wiki": "维基百科",
    "btc": "比特币", "中本聪币": "比特币",
    "大语言模型": "gpt", "AI模型": "gpt",
    "Attention机制": "transformer", "自注意力": "transformer",
    "大清": "清", "满清": "清",
    "蒙元": "元", "大元": "元",
    "狭义相对论": "相对论", "广义相对论": "相对论",
    "达尔文主义": "进化论", "自然选择学说": "进化论",
    "量子物理": "量子力学", "量子理论": "量子力学",
    "门捷列夫表": "元素周期表", "化学周期表": "元素周期表",
    "达尔文": "进化论",
    "爱因斯坦": "相对论",
    "互联网": "internet", "因特网": "internet", "网络": "internet",
    "AI": "人工智能", "机器学习": "人工智能",
    "飞行器": "飞机", "航空器": "飞机",
    "核武器": "核能", "原子能": "核能", "核弹": "核能",
}
KNOWLEDGE_BASE = {
    "秦": {"facts": ["秦朝是中国第一个大一统王朝，由秦始皇嬴政于公元前221年建立","秦朝于公元前207年灭亡","秦始皇没有发明火锅"], "source": "史记"},
    "汉": {"facts": ["汉朝分为西汉(前202-9年)和东汉(25-220年)","造纸术在西汉时期已有雏形，东汉蔡伦改进"], "source": "汉书"},
    "唐": {"facts": ["唐朝(618-907年)是中国历史上最繁荣的朝代之一","雕版印刷术在唐代发明","唐代首都是长安"], "source": "旧唐书"},
    "宋": {"facts": ["北宋(960-1127年)首都是开封","毕昇于北宋庆历年间发明活字印刷术","宋代出现了世界上最早的纸币交子"], "source": "宋史"},
    "明": {"facts": ["明朝(1368-1644年)由朱元璋建立","郑和七下西洋发生在明代永乐年间","明代北京故宫于1420年建成"], "source": "明史"},
    "python": {"facts": ["Python 由 Guido van Rossum 于 1991 年首次发布","Python 是解释型面向对象的高级编程语言","Python 的名字来源于 BBC 喜剧节目 Monty Python"], "source": "Python.org"},
    "linux": {"facts": ["Linux 内核由 Linus Torvalds 于 1991 年创建","Linux 是开源的类 Unix 操作系统内核"], "source": "kernel.org"},
    "http": {"facts": ["HTTP 协议由 Tim Berners-Lee 于 1989 年在 CERN 提出","HTTP 是超文本传输协议","第一个网站于 1991 年上线"], "source": "W3C"},
    "java": {"facts": ["Java 由 James Gosling 于 1995 年在 Sun Microsystems 发布","Java 最初的名字是 Oak"], "source": "Oracle"},
    "c语言": {"facts": ["C 语言由 Dennis Ritchie 于 1972 年在贝尔实验室开发","C 语言是为了写 Unix 而创造的"], "source": "计算机科学史"},
    "javascript": {"facts": ["JavaScript 由 Brendan Eich 于 1995 年在 Netscape 创建","JavaScript 与 Java 没有任何关系"], "source": "Mozilla"},
    "水": {"facts": ["水在标准大气压下沸点为 100°C，冰点为 0°C","水的化学式是 H2O","水在 4°C 时密度最大"], "source": "基础化学"},
    "光速": {"facts": ["光速不是无穷大的，光速是有限的", "光速约为每秒30万公里", "光速是宇宙中信息传播的极限速度"], "source": "物理学"},
    "dna": {"facts": ["DNA 双螺旋结构由 Watson 和 Crick 于 1953 年提出","Rosalind Franklin 的 X 射线衍射照片起关键作用"], "source": "Nature 1953"},
    "地球": {"facts": ["地球是太阳系第三颗行星，形成于约 45.4 亿年前","地球是已知唯一存在生命的天体","地球不是平的，地球是近似球体","地球不是完美球体"], "source": "NASA"},
    "珠穆朗玛峰": {"facts": ["珠穆朗玛峰是世界最高峰，海拔 8848.86 米","位于中国与尼泊尔边境"], "source": "中尼联合测量"},
    "火锅": {"facts": ["火锅的历史可追溯到战国时期","汉代已有类似火锅的青铜器皿","火锅不是单一起源"], "source": "中国饮食文化史"},
    "造纸": {"facts": ["造纸术是中国古代四大发明之一","西汉时期已有麻纸，东汉蔡伦改进"], "source": "后汉书"},
    "印刷": {"facts": ["雕版印刷术发明于唐代","毕昇于北宋庆历年间发明活字印刷术","古腾堡于 1450 年在欧洲发明铅活字印刷"], "source": "印刷史"},
    "内阁制度": {"facts": ["内阁制度是明朝永乐年间设立的不是朱元璋设立的","朱元璋时期废除的是丞相制度设立了锦衣卫","内阁首辅出现在明朝中后期张居正最著名"], "source": "明史·职官志"},
    "火药": {"facts": ["火药是中国古代四大发明之一，唐代已有记载","火药通过阿拉伯传入欧洲"], "source": "中国科学技术史"},
    "指南针": {"facts": ["指南针是中国古代四大发明之一","战国时期已有司南，宋代用于航海"], "source": "中国科学技术史"},
    "朱元璋": {"facts": ["朱元璋是明朝开国皇帝，1328-1398 年","朱元璋于1368年在应天（今南京）称帝建立明朝","朱元璋没有发明火锅，火锅远早于明代就已存在","朱元璋废除丞相制度设立锦衣卫"], "source": "明史"},
    "发明": {"facts": ["任何声称某人发明了某自然现象的断言都是错误的","四大发明专指造纸术、印刷术、火药、指南针"], "source": "常识"},
    "唯一": {"facts": ["包含唯一的断言几乎总是存在反例","声称某物是唯一的需要极其严格的证明"], "source": "逻辑学"},
    "第一": {"facts": ["声称世界第一的断言需要严格定义和证据","许多第一的宣称在学术上是争议的"], "source": "逻辑学"},
    "毕昇": {"facts": ["毕昇于北宋庆历年间发明活字印刷术","活字印刷是中国对世界文明的重大贡献"], "source": "梦溪笔谈"},
    "哥伦布": {"facts": ["哥伦布于1492年到达美洲","哥伦布不是第一个到达美洲的欧洲人，维京人Leif Erikson更早"], "source": "世界史"},
    "活字印刷": {"facts": ["毕昇于北宋庆历年间发明活字印刷术","古腾堡于1450年在欧洲发明铅活字印刷"], "source": "印刷史"},
    "太阳系": {"facts": ["太阳系最大的行星是木星","地球不是太阳系最大的行星","太阳系有8颗行星"], "source": "NASA"},
    "长城": {"facts": ["长城始建于春秋战国时期，秦始皇连接和扩建了北方长城","长城不是秦始皇一个人修建的","现存长城主要是明代修建的"], "source": "中国文化遗产"},
    "牛顿": {"facts": ["牛顿出生于1643年，逝世于1727年","艾萨克·牛顿于1687年发表《自然哲学的数学原理》","牛顿发现了万有引力定律和三大运动定律","牛顿和莱布尼茨分别独立发明了微积分","牛顿不是被苹果砸中才发现万有引力的——这是后来的传说"], "source": "科学史"},
    "爱因斯坦": {"facts": ["爱因斯坦于1905年发表狭义相对论，1915年发表广义相对论","爱因斯坦没有发明原子弹","E=mc²是狭义相对论的推论"], "source": "物理学史"},
    "爱迪生": {"facts": ["爱迪生没有发明电灯泡——电灯泡在他之前已经存在","爱迪生改进了灯泡并使其商业化","爱迪生持有1093项美国专利"], "source": "科技史"},
    "特斯拉": {"facts": ["尼古拉·特斯拉发明了交流电系统","特斯拉不是被埋没的天才——他在晚年获得了多项荣誉","特斯拉和爱迪生是竞争对手"], "source": "科技史"},
    "瓦特": {"facts": ["瓦特没有发明蒸汽机——他改良了蒸汽机使其效率大幅提高","蒸汽机在瓦特之前已存在数十年","瓦特的改良触发了工业革命"], "source": "科技史"},
    "贝尔": {"facts": ["亚历山大·贝尔于1876年获得电话专利","贝尔不是唯一发明电话的人——Elisha Gray同日提交了专利申请","贝尔的专利是历史上最有价值的专利之一"], "source": "科技史"},
    "莱特兄弟": {"facts": ["莱特兄弟于1903年12月17日完成首次动力飞行","莱特兄弟不是最早尝试飞行的人，但他们是第一个成功实现可控动力飞行的","首次飞行仅持续12秒，飞行距离36米"], "source": "航空史"},
    "莎士比亚": {"facts": ["威廉·莎士比亚是英国文艺复兴时期最伟大的剧作家","莎士比亚生于1564年，卒于1616年","莎士比亚的作品包括37部戏剧和154首十四行诗","莎士比亚不是一个人——关于其身份存在学术争议"], "source": "文学史"},
    "达尔文": {"facts": ["达尔文于1859年发表《物种起源》","达尔文不是第一个提出进化论的人——拉马克等人更早","自然选择是进化的主要机制"], "source": "《物种起源》"},
    "青霉素": {"facts": ["青霉素由亚历山大·弗莱明于1928年发现","弗莱明不是有意发现青霉素的——是实验室污染导致的意外发现","青霉素的发现标志着抗生素时代的开始","青霉素在二战期间大量生产，挽救了无数生命"], "source": "医学史"},
    "大脑": {"facts": ["人类只用了大脑10%的说法是完全没有科学依据的谣言","大脑只开发了10%是流传甚广的伪科学谣言——脑成像研究显示全脑都在活跃使用","人类大脑几乎所有区域都有功能，不存在90%未使用的部分","大脑约占体重的2%，但消耗约20%的能量","神经元不能再生是一个被推翻的旧观点——某些脑区确实可以产生新神经元"], "source": "神经科学"},
    "恐龙": {"facts": ["恐龙灭绝于约6600万年前的K-Pg灭绝事件","一颗小行星撞击地球是恐龙灭绝的主要原因","鸟类是恐龙的直接后代——鸟类不是恐龙的后代，鸟类就是恐龙的一种"], "source": "古生物学"},
    "蜜蜂": {"facts": ["根据物理定律，大黄蜂不能飞行的说法是都市传说","蜜蜂在采蜜时进行授粉","一只蜜蜂一生只能生产约十二分之一茶匙的蜂蜜"], "source": "昆虫学"},
    "咖啡": {"facts": ["咖啡原产于埃塞俄比亚","咖啡因是世界上消费最广泛的精神活性物质","咖啡不是山羊发现的——虽然有一个关于埃塞俄比亚牧羊人的传说"], "source": "食品史"},
    "茶": {"facts": ["茶起源于中国，传说神农氏发现了茶","唐代陆羽写了《茶经》，是世界第一部茶叶专著","下午茶的传统始于19世纪的英国"], "source": "茶文化史"},
    "巧克力": {"facts": ["巧克力起源于中美洲，玛雅人和阿兹特克人食用可可","现代固体巧克力在19世纪才发明","白巧克力不是真正的巧克力——它不含可可固体"], "source": "食品史"},
    "维基百科": {"facts": ["维基百科于2001年1月15日上线","维基百科由Jimmy Wales和Larry Sanger创建","维基百科是世界最大的百科全书"], "source": "维基媒体基金会"},
    "比特币": {"facts": ["比特币于2009年由化名中本聪的人创建","中本聪的真实身份至今未知","比特币的总量上限是2100万个"], "source": "bitcoin.org"},
    "万有引力": {"facts": ["万有引力定律由牛顿提出","万有引力不是牛顿看到苹果落地后顿悟的——他研究这个问题多年，牛顿也没有被苹果砸中","引力是四种基本力中最弱的"], "source": "物理学"},
    "氧气": {"facts": ["氧气由约瑟夫·普里斯特利和卡尔·舍勒分别独立发现","氧气占地球大气的约21%","氧气不是可燃的——它是助燃的"], "source": "化学史"},
    "二氧化碳": {"facts": ["二氧化碳的化学式是CO2","二氧化碳是温室气体","植物通过光合作用将二氧化碳转化为氧气"], "source": "化学"},
    "月球": {"facts": ["月球是地球唯一的天然卫星","月球不是自己发光的——它反射太阳光","人类首次登月是1969年阿波罗11号任务"], "source": "NASA"},
    "太阳": {"facts": ["太阳是太阳系的中心恒星","太阳是一颗G型主序星(黄矮星)","太阳占太阳系总质量的99.86%"], "source": "NASA"},
    "木星": {"facts": ["木星是太阳系最大的行星","木星有著名的大红斑——一个持续了数百年的风暴","木星有超过90颗已知卫星"], "source": "NASA"},
    "火星": {"facts": ["火星被称为红色行星","火星上目前没有发现液态水的存在","火星有两颗卫星：火卫一和火卫二"], "source": "NASA"},
    "gpt": {"facts": ["GPT是Generative Pre-trained Transformer的缩写","GPT系列由OpenAI开发","GPT-1于2018年发布，GPT-3于2020年发布"], "source": "OpenAI"},
    "transformer": {"facts": ["Transformer架构于2017年在论文Attention Is All You Need中提出","Transformer是当前大多数大语言模型的基础架构","Transformer的核心创新是自注意力机制"], "source": "Vaswani et al. 2017"},
    "围棋": {"facts": ["围棋起源于中国，有超过2500年的历史","围棋是最复杂的棋类游戏之一","AlphaGo于2016年击败李世石是AI历史的重要里程碑"], "source": "围棋史"},
    "马拉松": {"facts": ["马拉松的距离是42.195公里","马拉松的距离不是从希腊传令兵菲迪皮德斯的故事来的——现代距离是1908年伦敦奥运会上确定的","菲迪皮德斯跑了约40公里从马拉松到雅典报捷"], "source": "奥林匹克历史"},
    
    "清": {"facts": ["清朝(1644-1912年)是中国最后一个封建王朝","鸦片战争于1840年爆发，中国被迫打开国门","清朝由满族人建立，前身为后金"], "source": "清史稿"},
    "元": {"facts": ["元朝(1271-1368年)由忽必烈建立","元朝是中国历史上疆域最广阔的朝代之一","马可·波罗在元朝时期来到中国"], "source": "元史"},
    "三国": {"facts": ["三国时期(220-280年)是魏蜀吴三足鼎立的时代","赤壁之战发生在208年","三国不是由曹操统一的——最终由司马炎统一"], "source": "三国志"},
    "丝绸之路": {"facts": ["丝绸之路始于汉代，张骞出使西域开辟","丝绸之路不仅运输丝绸，还传播文化和技术","海上丝绸之路与陆上丝绸之路并行发展"], "source": "中外交通史"},
    "相对论": {"facts": ["狭义相对论由爱因斯坦于1905年提出","广义相对论于1915年提出","E=mc²是狭义相对论最著名的公式","相对论推翻了牛顿的绝对时空观"], "source": "物理学"},
    "进化论": {"facts": ["达尔文于1859年出版《物种起源》","进化论的核心机制是自然选择","进化论不是人是从猴子变来的——人和猴子有共同祖先","达尔文没有说适者生存——这是斯宾塞的说法"], "source": "生物学"},
    "量子力学": {"facts": ["量子力学于20世纪初由普朗克、玻尔、海森堡等人建立","量子力学描述微观世界的物理规律","量子纠缠是真实存在的物理现象","薛定谔的猫是一个思想实验，不是真实实验"], "source": "物理学"},
    
    "故宫": {"facts": ["故宫位于北京，不在纽约","故宫是明清两代的皇家宫殿，于1420年建成","故宫旧称紫禁城"], "source": "故宫博物院"},
    "富士山": {"facts": ["富士山位于日本，不在中国","富士山是日本最高峰，海拔3776米","富士山是一座活火山"], "source": "日本地理"},
    "元素周期表": {"facts": ["元素周期表由门捷列夫于1869年提出","门捷列夫准确预测了当时尚未发现的元素","元素周期表按原子序数排列，不是原子量"], "source": "化学"},
    "电": {"facts": ["电是自然现象，不是任何人发明的","本杰明·富兰克林没有发明电——他证明了闪电是电","法拉第发现了电磁感应定律"], "source": "物理学"},
    "internet": {"facts": ["互联网起源于1969年的ARPANET","万维网由Tim Berners-Lee于1989年发明","互联网和万维网不是同一个概念——万维网运行在互联网之上"], "source": "计算机科学"},
    "人工智能": {"facts": ["人工智能作为一个研究领域始于1956年达特茅斯会议","图灵于1950年提出图灵测试","AI不是万能的——当前AI是窄人工智能而非通用人工智能"], "source": "计算机科学"},
    "飞机": {"facts": ["莱特兄弟于1903年进行了首次动力飞行","莱特兄弟不是第一个飞上天空的人——滑翔机和气球更早出现","喷气式飞机在二战后期才投入实战"], "source": "航空史"},
    "疫苗": {"facts": ["爱德华·詹纳于1796年发明了天花疫苗——世界上第一种疫苗","疫苗通过激发免疫系统产生抗体来预防疾病","疫苗不会导致自闭症——这个说法来自一篇被撤稿的造假论文"], "source": "医学"},
    "核能": {"facts": ["恩里科·费米于1942年建造了第一个核反应堆","核裂变于1938年由哈恩和斯特拉斯曼发现","第一颗原子弹于1945年在新墨西哥州试爆"], "source": "物理学"},
    "奥林匹克": {"facts": ["现代奥运会始于1896年，在雅典举行","奥林匹克休战是古希腊的传统","奥运会金牌不是纯金的——主要是银，镀了一层金"], "source": "国际奥委会"},

    "黄帝": {"facts": ["黄帝是传说中中华民族的人文初祖","黄帝不是第一个皇帝——皇帝制度始于秦始皇","黄帝和炎帝并称炎黄，是华夏族的共同祖先"], "source": "史记"},
    "司马迁": {"facts": ["司马迁是西汉历史学家，著有《史记》","司马迁遭受宫刑后完成了《史记》","《史记》是中国第一部纪传体通史"], "source": "汉书"},
    "孙子兵法": {"facts": ["《孙子兵法》由春秋时期孙武所著","《孙子兵法》是世界上最早的兵书之一","孙子兵法不是现代管理学著作——但其中的策略被广泛借用"], "source": "中国军事史"},
    "拿破仑": {"facts": ["拿破仑·波拿巴于1804年称帝","拿破仑不是矮子——他身高约168-170厘米，高于当时的法国平均水平","滑铁卢战役发生于1815年，拿破仑在此战败"], "source": "欧洲史"},
    "文艺复兴": {"facts": ["文艺复兴于14-17世纪发源于意大利","文艺复兴不是突然出现的——它根植于中世纪晚期的社会变化","达芬奇、米开朗基罗和拉斐尔是文艺复兴三杰"], "source": "艺术史"},
    "工业革命": {"facts": ["第一次工业革命始于18世纪60年代的英国","工业革命不是由单一发明触发的——是纺织、蒸汽机、冶金等多个领域的综合变革","工业革命极大地改变了人类社会的生活方式"], "source": "经济史"},
    "法国大革命": {"facts": ["法国大革命爆发于1789年","攻占巴士底狱是法国大革命的标志性事件","法国大革命提出了自由、平等、博爱的口号"], "source": "欧洲史"},
    "十月革命": {"facts": ["十月革命发生于1917年11月7日（俄历10月25日）","十月革命不是唯一的俄国革命——同年二月革命已推翻了沙皇","十月革命建立了世界上第一个社会主义国家"], "source": "俄国史"},
    "圆周率": {"facts": ["圆周率π是一个无限不循环小数","π约等于3.14159","祖冲之在5世纪将π计算到小数点后7位","π不是3.14——3.14只是一个近似值"], "source": "数学"},
    "勾股定理": {"facts": ["勾股定理描述直角三角形三边关系：a²+b²=c²","勾股定理在中国古代由商高发现，西方称为毕达哥拉斯定理","勾股定理不是毕达哥拉斯第一个发现的——古巴比伦人更早"], "source": "数学"},
    "黄金分割": {"facts": ["黄金分割比例约为1:1.618","黄金分割在自然界和艺术中广泛存在","黄金分割不是美的唯一标准——很多经典作品并不遵循黄金分割"], "source": "数学"},
    "撒哈拉": {"facts": ["撒哈拉沙漠是世界上最大的热沙漠","撒哈拉不是世界上最大的沙漠——南极洲是最大的沙漠","撒哈拉曾经是绿洲，约1万年前气候湿润"], "source": "地理"},
    "尼罗河": {"facts": ["尼罗河是世界上最长的河流之一","尼罗河每年定期泛滥为古埃及农业提供了肥沃的土壤","尼罗河的源头之争持续了数千年"], "source": "地理"},
    "亚马逊": {"facts": ["亚马逊雨林是世界上最大的热带雨林","亚马逊雨林不是地球之肺——海洋产生更多氧气","亚马逊河是世界上流量最大的河流"], "source": "地理"},
    "蓝鲸": {"facts": ["蓝鲸是地球上已知最大的动物","蓝鲸不是鱼——是哺乳动物","蓝鲸以磷虾为食，每天可消耗数吨磷虾"], "source": "生物学"},
    "章鱼": {"facts": ["章鱼有3个心脏和9个大脑","章鱼是非常聪明的无脊椎动物","章鱼血液是蓝色的——因为含有血蓝蛋白而非血红蛋白"], "source": "生物学"},
    "维生素c": {"facts": ["维生素C又称抗坏血酸","缺乏维生素C会导致坏血病","维生素C不能预防感冒——这个说法缺乏科学证据"], "source": "营养学"},
    "莫扎特": {"facts": ["沃尔夫冈·阿马德乌斯·莫扎特是天才作曲家","莫扎特5岁开始作曲，35岁去世","莫扎特不是被萨列里毒死的——这是电影《莫扎特传》的虚构情节"], "source": "音乐史"},
    "红楼梦": {"facts": ["《红楼梦》是中国古典四大名著之一","《红楼梦》前80回由曹雪芹所著，后40回一般认为是高鹗续写","《红楼梦》不是爱情小说——它是一部封建社会的百科全书"], "source": "中国文学"},
    "足球": {"facts": ["现代足球起源于英国","足球不是英国发明的——古代中国和古希腊都有类似运动","世界杯足球赛始于1930年"], "source": "体育"},
    "通货膨胀": {"facts": ["通货膨胀是货币购买力持续下降的现象","通货膨胀不是物价上涨——物价上涨是通货膨胀的表现","适度的通货膨胀是经济增长的正常现象"], "source": "经济学"},
    "半导体": {"facts": ["半导体是导电性介于导体和绝缘体之间的材料","硅是最常用的半导体材料","摩尔定律预测集成电路上晶体管数量约每两年翻一番"], "source": "电子学"},
    "图灵": {"facts": ["艾伦·图灵是计算机科学的奠基人","图灵在二战期间破解了德国的恩尼格玛密码","图灵不是发明计算机的人——他提出了通用计算机的理论模型","图灵测试是判断机器是否具有智能的方法"], "source": "计算机科学"},
    "冥王星": {"facts": ["冥王星于2006年被降级为矮行星","冥王星不是太阳系最小的天体——它仍然是柯伊伯带中最大的天体之一","冥王星由克莱德·汤博于1930年发现"], "source": "天文学"},
    "土星": {"facts": ["土星是太阳系第二大行星","土星环主要由冰和岩石碎片组成","土星不是唯一有环的行星——木星、天王星和海王星也有环"], "source": "天文学"},


    "孔子": {"facts": ["孔子名丘，字仲尼，春秋时期鲁国人","孔子是儒家学派创始人","孔子不是《论语》的作者——《论语》是其弟子及再传弟子编纂的","孔子周游列国不是自愿旅行——是被迫的政治流亡"], "source": "史记"},
    "老子": {"facts": ["老子姓李名耳，春秋时期人","老子是道家学派创始人","《道德经》是否为老子本人所著存在学术争议","老子不是道教创始人——道教是东汉张道陵创立的"], "source": "史记"},
    "柏拉图": {"facts": ["柏拉图是古希腊哲学家，苏格拉底的学生","柏拉图创立了雅典学院","柏拉图不是第一个提出理想国概念的人——但他将其系统化了","柏拉图认为诗人应该被逐出理想国"], "source": "西方哲学史"},
    "亚里士多德": {"facts": ["亚里士多德是柏拉图的学生，亚历山大大帝的老师","亚里士多德不是所有科学之父——他的一些科学观点已被证明错误","亚里士多德认为重物比轻物下落更快——这是错的","亚里士多德著作涵盖逻辑学、物理学、生物学、伦理学等"], "source": "西方哲学史"},
    "罗马帝国": {"facts": ["罗马帝国不是一天建成的","罗马帝国分裂为东西两部分——西罗马于476年灭亡，东罗马持续到1453年","罗马不是世界上最大的帝国——大英帝国和蒙古帝国的面积更大","罗马帝国不是突然崩溃的——经历了几百年的衰落过程"], "source": "世界史"},
    "二战": {"facts": ["第二次世界大战于1939年爆发，1945年结束","二战不是由单一事件引发的——是多重因素累积的结果","中国抗日战争是二战的重要组成部分","原子弹不是结束二战的唯一原因——苏联对日宣战也是关键因素"], "source": "世界史"},
    "冷战": {"facts": ["冷战是二战后美苏两大阵营的对峙","冷战没有变成热战——但期间有许多代理人战争","冷战不是以一方投降结束的——苏联解体标志着冷战终结","柏林墙于1961年建立，1989年倒塌"], "source": "世界史"},
    "黑洞": {"facts": ["黑洞是由大质量恒星坍缩形成的天体","黑洞不是洞——它是一个密度极大的天体","黑洞不是只进不出的——霍金辐射理论认为黑洞会蒸发","黑洞不是爱因斯坦预言的——是广义相对论方程的一个解"], "source": "天文学"},
    "暗物质": {"facts": ["暗物质是宇宙中不发光的物质，占宇宙总质量的约27%","暗物质不是被证明存在的——目前通过引力效应间接推断","暗物质不是反物质——两者是不同的概念","暗物质可能由未知粒子组成"], "source": "物理学"},
    "大陆漂移": {"facts": ["大陆漂移学说由魏格纳于1912年提出","魏格纳不是第一个注意到大陆形状吻合的人——但他系统论证了","大陆漂移已被板块构造理论取代和完善","大陆不是漂浮在水上的——是漂浮在地幔上的"], "source": "地质学"},
    "光合作用": {"facts": ["光合作用是植物将光能转化为化学能的过程","光合作用不是植物独有的——某些细菌也能进行","光合作用释放氧气是副产物","植物不是只靠光合作用生存——夜间进行呼吸作用消耗氧气"], "source": "生物学"},
    "气候变暖": {"facts": ["全球气候变暖是指地球平均气温持续上升","气候变暖不是自然周期——当前暖化速度远超历史上任何自然周期","97%以上的气候科学家认同人类活动是主因","气候变暖不是只让地球变热——还导致极端天气增加"], "source": "IPCC"},
    "蓝牙": {"facts": ["蓝牙技术于1994年由爱立信公司发明","蓝牙不是十世纪丹麦国王发明的——虽然以他的名字命名","蓝牙低功耗模式于2010年随蓝牙4.0引入","蓝牙的有效距离通常为10-100米，不是无限距离"], "source": "通信技术"},
    "wifi": {"facts": ["WiFi是基于IEEE 802.11标准的无线网络技术","WiFi不是由单一个人发明的——是多方技术融合的产物","WiFi不是无线上网的唯一方式——蜂窝数据也是","WiFi这个名称不是Wireless Fidelity的缩写——只是一种品牌命名"], "source": "通信技术"},
    "区块链": {"facts": ["区块链是一种去中心化的分布式账本技术","区块链不等于比特币——比特币是区块链的第一个应用","区块链不是不可篡改的——51%攻击可以改写历史","区块链不是万能解决方案——许多场景不需要区块链"], "source": "计算机科学"},
    "蒙娜丽莎": {"facts": ["《蒙娜丽莎》是达芬奇于16世纪初创作的油画","蒙娜丽莎不是达芬奇唯一的作品——但确实是最著名的","《蒙娜丽莎》的微笑之谜可能只是达芬奇的sfumato技法","《蒙娜丽莎》不是被盗后才出名的——它被盗前已经很有名"], "source": "艺术史"},
    "梵高": {"facts": ["文森特·梵高是荷兰后印象派画家","梵高生前只卖出了一幅画——《红色葡萄园》","梵高不是割掉整个耳朵的——他只割掉了左耳的一部分","梵高不是因无人赏识而死——他患有精神疾病"], "source": "艺术史"},
    "毕加索": {"facts": ["巴勃罗·毕加索是20世纪最有影响力的艺术家之一","毕加索创立了立体主义画派","毕加索不是只会画抽象画——他早期的写实作品技艺精湛","《格尔尼卡》是毕加索反战题材的代表作"], "source": "艺术史"},
    "西游记": {"facts": ["《西游记》是中国古典四大名著之一","《西游记》作者一般认为是明代吴承恩","《西游记》不是佛教宣传书——它融合了儒释道三家思想","孙悟空的原型存在多种说法，尚无定论"], "source": "中国文学"},
    "三国演义": {"facts": ["《三国演义》是元末明初罗贯中所著","《三国演义》不是历史——是一部历史演义小说","《三国演义》中许多情节是虚构的——如草船借箭实际上不是诸葛亮所为","关羽使用的不是青龙偃月刀——这种兵器在三国时期还不存在"], "source": "中国文学"},
    "水浒传": {"facts": ["《水浒传》是中国古典四大名著之一","《水浒传》的故事背景是北宋末年宋江起义","《水浒传》108将大多不是真实历史人物——只有36人是历史记载的","林冲、武松等核心角色在正史中没有记载"], "source": "中国文学"},
    "死海": {"facts": ["死海是世界上海拔最低的湖泊","死海不是海——是一个内陆盐湖","死海的含盐量约为普通海水的10倍","死海中并非完全没有生命——存在嗜盐微生物"], "source": "地理"},
    "大堡礁": {"facts": ["大堡礁位于澳大利亚东北海岸，是世界上最大的珊瑚礁系统","大堡礁不是从一个太空可见的地球结构——它是少数几个可见的之一","大堡礁正在受气候变化和珊瑚白化的威胁","大堡礁的年龄约为50万年，不是从恐龙时代就存在的"], "source": "地理"},
    "黄石公园": {"facts": ["黄石国家公园位于美国，是世界上第一个国家公园","黄石公园坐落在一座超级火山上","黄石超级火山不会很快喷发——目前没有即将喷发的迹象","黄石公园不是美国最大的国家公园"], "source": "地理"},
    "南极洲": {"facts": ["南极洲是地球上最冷的大陆，平均温度约-57°C","南极洲不是没有生命——有企鹅、海豹和多种微生物","南极洲冰层储存了地球约70%的淡水","南极洲不属于任何国家——受《南极条约》保护"], "source": "地理"},
    "珊瑚": {"facts": ["珊瑚是动物，不是植物","珊瑚礁由珊瑚虫分泌的碳酸钙骨骼构成","珊瑚白化是由于共生藻类离开导致的","珊瑚不是石头——活的珊瑚是柔软的珊瑚虫群落"], "source": "生物学"},
    "蝙蝠": {"facts": ["蝙蝠是唯一能够飞行的哺乳动物","蝙蝠不是瞎子——大多数蝙蝠视力很好","蝙蝠不会主动攻击人类——吸血蝙蝠只分布于拉丁美洲","蝙蝠对生态系统至关重要——是重要的传粉者和害虫控制者"], "source": "生物学"},
    "蚂蚁": {"facts": ["蚂蚁在地球上已存在超过1亿年","蚂蚁的社会结构不是君主制——蚁后只是产卵机器","地球上蚂蚁的总重量超过所有人类的总重量","蚂蚁不是完全盲目的——它们依靠信息素导航和通讯"], "source": "生物学"},
    "蜘蛛": {"facts": ["蜘蛛不是昆虫——属于蛛形纲","不是所有蜘蛛都织网——狼蛛等猎食性蜘蛛不织网","蜘蛛丝比同等重量的钢更强韧","大多数蜘蛛对人类无害"], "source": "生物学"},
    "麻醉": {"facts": ["现代麻醉术始于1846年波士顿的乙醚麻醉演示","麻醉不是让人睡着——是诱导可逆的意识丧失和痛觉消失","中国古代华佗的麻沸散存在争议——缺乏可靠史料证实","麻醉不是万无一失的——需要专业麻醉医师全程监控"], "source": "医学史"},
    "x光": {"facts": ["X射线由威廉·伦琴于1895年发现","X光不是伦琴刻意寻找的——他在做阴极射线实验时意外发现","第一张X光片是伦琴夫人的手","X光不是完全无害的——高剂量辐射有致癌风险"], "source": "医学史"},
    "dna测序": {"facts": ["第一个人类基因组测序于2003年完成——人类基因组计划","DNA测序不是从2000年才开始——桑格测序法于1977年发明","DNA测序的成本不是不变的——从最初的数十亿美元降到了几百美元","DNA测序不能预测你的一切——基因只决定一部分特征"], "source": "基因组学"},
    "弗洛伊德": {"facts": ["西格蒙德·弗洛伊德是精神分析学创始人","弗洛伊德的理论不是科学界普遍接受的——许多理论已被现代心理学抛弃","弗洛伊德不是发现潜意识的第一人——这个概念在他之前就存在","弗洛伊德不是心理学家——他是神经科医生"], "source": "心理学史"},
    "安慰剂效应": {"facts": ["安慰剂效应是指病人因相信自己接受治疗而产生真实改善","安慰剂效应不是假的——它能在脑中产生真实的生理变化","安慰剂效应不能治愈癌症——但可以缓解某些症状","安慰剂不是无用的——它在临床试验和某些治疗中有重要价值"], "source": "医学"},
    "认知偏差": {"facts": ["认知偏差是系统性偏离理性判断的思维模式","确认偏误是人们倾向于寻找支持自己观点的证据","认知偏差不是智商问题——高智商的人同样会有认知偏差","认知偏差不是少数人的问题——每个人都会受到各种认知偏差的影响"], "source": "心理学"},
    "居里夫人": {"facts": ["玛丽·居里是第一位获得诺贝尔奖的女性","居里夫人发现了放射性元素镭和钋","居里夫人是唯一获得过两次诺贝尔奖的女性科学家","居里夫人死于再生障碍性贫血，可能与长期接触辐射有关","居里夫人的笔记本至今仍有放射性"], "source": "科学史"},
    "诺贝尔奖": {"facts": ["诺贝尔奖由阿尔弗雷德·诺贝尔于1895年设立","诺贝尔不是因为内疚才设立和平奖的——但这件事被广泛传播","诺贝尔奖没有数学奖——不是因为诺贝尔的恋人跟数学家跑了","诺贝尔经济学奖不是诺贝尔本人设立的——由瑞典央行于1968年设立"], "source": "科学史"},
    "三角形": {"facts": ["三角形内角和等于180度","三角形内角和不是永远180度——在非欧几何中可以大于或小于180度","勾股定理是描述直角三角形三边关系的定理","三角形是最稳定的几何结构之一"], "source": "数学"},
    "素数": {"facts": ["素数只能被1和自身整除","1不是素数","有无穷多个素数——欧几里得在公元前300年就证明了","最大的已知素数有数千万位数——由分布式计算项目找到"], "source": "数学"},
    "零": {"facts": ["零作为数字的概念最早由古印度数学家提出","零不是自然产生的概念——人类花了很长时间才接受零作为数字","零不能作为除数","阿拉伯数字中的零符号是通过阿拉伯人传入欧洲的"], "source": "数学史"},
    "地震": {"facts": ["地震是由地壳板块运动或火山活动引起的","地震不是可以被精确预测的——目前无法预测具体时间和地点","地震的震级不是线性的——每增加1级，释放的能量约增加32倍","动物不是总能预测地震——这个说法缺乏一致的科学证据"], "source": "地质学"},
    "火山": {"facts": ["火山是地球内部岩浆喷出地表形成的","火山喷发不是随机事件——通常有前兆如地震和地面变形","火山不是只会破坏——火山灰使土壤肥沃","休眠火山不是死火山——有再次喷发的可能"], "source": "地质学"},
    "睡眠": {"facts": ["成年人每晚需要7-9小时睡眠","睡眠不是统一状态——分为REM和非REM睡眠周期","补觉不能完全弥补缺觉的损害","睡眠不是浪费时间——记忆巩固和身体修复都在睡眠中进行"], "source": "生理学"},
    "梦境": {"facts": ["每个人每晚都会做多个梦——但不一定记得","梦不是有颜色的——大多数人的梦是有颜色的","梦不是一定有意义——许多梦只是大脑随机神经活动的产物","盲人的梦不是没有视觉——先天盲人的梦以声音和触觉为主"], "source": "心理学"},
    "酸奶": {"facts": ["酸奶是通过乳酸菌发酵制成的乳制品","酸奶不是所有细菌都对人体有益——只有特定益生菌株","酸奶不能治疗所有消化问题","酸奶的历史超过4000年——可能起源于中亚"], "source": "食品科学"},
    "辣椒": {"facts": ["辣椒的辣味来自辣椒素","辣椒不是原产于中国——它原产于美洲，明代才传入中国","吃辣不是味觉——辣是痛觉感受器被激活","四川人不是自古以来就吃辣——辣椒传入四川不超过400年"], "source": "食物史"},
    "土豆": {"facts": ["土豆原产于南美洲安第斯山区","土豆不是欧洲人发明的——16世纪才从美洲传入","土豆不是蔬菜——从营养学角度更接近主食","炸薯条不是法国人发明的——比利时人也声称发明权"], "source": "食物史"},
    "黄金": {"facts": ["黄金是地球上最稀有的贵金属之一","黄金不是来自地球——超新星爆炸或中子星碰撞产生金元素","黄金不是不会腐蚀——它只是化学反应性极低","地球上所有的黄金总量大约只能填满三个奥运会游泳池"], "source": "化学"},
    "声音": {"facts": ["声音通过介质传播，真空中无法传播","声音的速度不是固定的——在空气中约340m/s，在水中约1500m/s","超声波的频率超过人类听觉范围","声音不是能量——是机械振动在介质中的传播"], "source": "物理学"},


    "达尔文": {"facts": ["查尔斯·达尔文于1859年发表《物种起源》","达尔文提出了自然选择进化论","达尔文不是第一个提出进化的人——拉马克更早","进化论不是达尔文独自发现的——华莱士也独立提出了自然选择"], "source": "《物种起源》"},
    "爱因斯坦": {"facts": ["阿尔伯特·爱因斯坦于1905年发表狭义相对论","爱因斯坦于1915年发表广义相对论","爱因斯坦不是原子弹的发明者——他签署了呼吁信但未参与曼哈顿计划","质能方程E=mc²由爱因斯坦提出"], "source": "物理学史"},
    "牛顿": {"facts": ["艾萨克·牛顿于1687年发表《自然哲学的数学原理》","牛顿提出了万有引力定律和三大运动定律","牛顿和莱布尼茨各自独立发明了微积分","牛顿没有被苹果砸中——这是后人编造的故事"], "source": "物理学史"},
    "特斯拉": {"facts": ["尼古拉·特斯拉是交流电系统的发明者","特斯拉不是交流电的唯一发明者——他与爱迪生的直流电竞争","特斯拉线圈是特斯拉发明的"], "source": "电子学"},
    "爱迪生": {"facts": ["托马斯·爱迪生是美国发明家","爱迪生没有发明电灯——他改进了电灯使其商业化","爱迪生发明了留声机和电影摄影机","爱迪生不是第一个发明白炽灯的人——斯旺更早获得专利"], "source": "科技史"},
    "瓦特": {"facts": ["詹姆斯·瓦特改进了蒸汽机使其效率大幅提高","瓦特不是第一个发明蒸汽机的人——纽科门更早发明了蒸汽机","瓦特的蒸汽机是工业革命的关键推动力"], "source": "科技史"},
    "爱因斯坦相对论": {"facts": ["爱因斯坦的相对论不是推翻牛顿力学——牛顿力学是低速近似","狭义相对论发表于1905年","广义相对论发表于1915年"], "source": "物理学"},
    "进化论": {"facts": ["达尔文于1859年发表《物种起源》系统阐述进化论","进化论的核心是自然选择","进化论不是'人是从猴子变的'——人和现代猿有共同祖先"], "source": "生物学"},
    "恐龙": {"facts": ["非鸟恐龙灭绝于约6600万年前的白垩纪末","恐龙灭绝的主要原因是小行星撞击","恐龙不是冷血动物——许多恐龙是温血动物","鸟类是恐龙的后代"], "source": "古生物学"},
    "蜜蜂": {"facts": ["蜜蜂不是唯一会采蜜的昆虫","蜜蜂通过舞蹈传递食物位置信息","蜂群崩溃综合症是全球蜜蜂减少的原因之一"], "source": "昆虫学"},
    "咖啡因": {"facts": ["咖啡因是一种中枢神经兴奋剂","咖啡因不会导致脱水——适量饮用与水效果相当","茶和咖啡都含有咖啡因"], "source": "食品科学"},
    "抗生素": {"facts": ["抗生素对病毒感染无效","青霉素是第一个抗生素，由弗莱明于1928年发现","抗生素滥用导致耐药菌增加"], "source": "医学"},
    "维生素d": {"facts": ["维生素D主要通过皮肤晒太阳合成","维生素D不是越多越好——过量会引起中毒","缺乏维生素D会导致佝偻病"], "source": "医学"},
    "太阳": {"facts": ["太阳是太阳系的中心恒星","太阳不是宇宙中最大的恒星","太阳主要由氢和氦组成","太阳的寿命约为100亿年，目前已过约46亿年"], "source": "天文学"},
    "月球": {"facts": ["月球是地球唯一的天然卫星","月球上没有大气层和水","人类首次登月是1969年阿波罗11号","月球不是由绿色奶酪构成的"], "source": "天文学"},
    "火星": {"facts": ["火星是太阳系第四颗行星","火星没有液态水在表面稳定存在","火星不是红色的——它呈红色是因为表面有氧化铁"], "source": "NASA"},
    "企鹅": {"facts": ["企鹅是鸟类，不是哺乳动物","企鹅不会飞","企鹅生活在南半球，北极没有企鹅"], "source": "生物学"},
    "北极熊": {"facts": ["北极熊生活在北极地区","北极熊的皮肤是黑色的，毛是无色透明的","北极熊和企鹅不会在野外相遇"], "source": "生物学"},
    "重力": {"facts": ["重力是万有引力在地球表面的表现","重力加速度约为9.8m/s²","重力不是均匀的——地球不同位置重力略有差异"], "source": "物理学"},
    "比特币": {"facts": ["比特币由中本聪于2009年创建","比特币的总量上限是2100万个","比特币不是第一个数字货币——但它解决了双花问题","比特币不是匿名的——是假名的"], "source": "bitcoin.org"},
}

# KB 并发写锁
_kb_lock = threading.Lock()

# 合并用户贡献的知识库
try:
    import json as _json
    from pathlib import Path as _Path
    _user_kb_path = _Path(__file__).parent / "kb_user.json"
    if _user_kb_path.exists():
        _MAX_KB_FILE_SIZE = 10 * 1024 * 1024  # 10MB
        if _user_kb_path.stat().st_size > _MAX_KB_FILE_SIZE:
            import sys as _sys
            print(f"警告: kb_user.json 过大 ({_user_kb_path.stat().st_size} 字节)，跳过加载", file=_sys.stderr)
        else:
            with open(_user_kb_path) as _f:
                _user_kb = _json.load(_f)
        _user_count = 0
        _MAX_USER_KB_ENTRIES = 200
        _MAX_KEY_LEN = 80
        for _key, _entry in _user_kb.items():
            if _key.startswith("_"):
                continue
            if len(_key) > _MAX_KEY_LEN or not _key.replace("_", "").replace("-", "").isalnum():
                continue  # 拒绝非法键名
            _user_count += 1
            if _user_count > _MAX_USER_KB_ENTRIES:
                break
            if _key in KNOWLEDGE_BASE:
                _existing = set(KNOWLEDGE_BASE[_key]["facts"])
                for _fct in _entry.get("facts", []):
                    if _fct not in _existing and len(_fct) < 500:
                        KNOWLEDGE_BASE[_key]["facts"].append(_fct)
            else:
                KNOWLEDGE_BASE[_key] = _entry
except (FileNotFoundError, json.JSONDecodeError, OSError):
    pass  # 用户KB损坏时不影响核心功能

# 合并自动生成的知识库 (kb_core.json)
try:
    _core_kb_path = _Path(__file__).parent / "kb_core.json"
    if _core_kb_path.exists():
        with open(_core_kb_path) as _f:
            _core_kb = _json.load(_f)
        _added = 0
        for _key, _entry in _core_kb.items():
            if _key.startswith("_"):
                continue
            if _key in KNOWLEDGE_BASE:
                _existing = set(KNOWLEDGE_BASE[_key]["facts"])
                for _fct in _entry.get("facts", []):
                    if _fct not in _existing:
                        KNOWLEDGE_BASE[_key]["facts"].append(_fct)
                        _added += 1
            else:
                KNOWLEDGE_BASE[_key] = _entry
                _added += 1
        log.info("kb_core merged", new_keys=_added)
except (FileNotFoundError, json.JSONDecodeError, OSError):
    pass


# ── 通用常识知识库（补充西方/全球话题）──
try:
    from commonsense_kb import COMMONSENSE_KB
    added = sum(1 for k in COMMONSENSE_KB if k not in KNOWLEDGE_BASE)
    KNOWLEDGE_BASE.update(COMMONSENSE_KB)
    log.info(f"commonsense merged | added_keys={added}")
except ImportError:
    pass






# ============================================================
# 数据结构
# ============================================================

@dataclass
class FactualClaim:
    """提取出的断言"""
    text: str
    entities: list[str]
    is_verifiable: bool
    confidence: float  # 模型自信度 (如可用 logprobs 则来自 logprobs)


@dataclass
class VerificationResult:
    """核查结果"""
    claim: str
    verdict: str          # verified / contradicted / uncertain / unverifiable
    confidence: float
    evidence: str
    source: str
    anchor_type: str      # knowledge_base / web_search / consistency / none


@dataclass
class HallucinationReport:
    """完整报告 — 含预测加工可解释性"""
    input_text: str
    claims: list[FactualClaim] = field(default_factory=list)
    results: list[VerificationResult] = field(default_factory=list)
    overall_score: float = 1.0
    hallucination_ratio: float = 0.0
    warnings: list[str] = field(default_factory=list)
    predictive_processing: dict = field(default_factory=dict)


# ============================================================
# 事实提取器
# ============================================================

class FactExtractor:
    """从文本中提取可核查的断言"""

    # 断言标记词
    ASSERTION_PATTERNS = [
        (r"(.+?)是(.+?)(?:的|。|，|$)", "is_statement"),
        (r"(.+?)发明了(.+?)(?:。|，|$)", "invention"),
        (r"(.+?)创建了(.+?)(?:。|，|$)", "creation"),
        (r"(.+?)于(\d+)年(.+?)(?:。|，|$)", "dated_event"),
        (r"(.+?)位于(.+?)(?:。|，|$)", "location"),
        (r"(.+?)在(.+?)(?:。|，|$)", "location"),
        (r"(.+?)绝对(.+?)(?:。|，|$)", "absolute_claim"),
        (r"(.+?)从来(.+?)(?:。|，|$)", "absolute_claim"),
        (r"(.+?)一定(.+?)(?:。|，|$)", "absolute_claim"),
    ]

    # 无信息量的表述（跳过）
    SKIP_PATTERNS = [
        r"^(好的|嗯|哦|哈哈|谢谢|再见|你好)",
        r"^(可以|没问题|当然|是的|对的)",
        r"^根据我的",
        r"^让我",
        r"^以下",
        r"^需要注意",
    ]

    @classmethod
    def extract(cls, text: str) -> list[FactualClaim]:
        claims = []
        sentences = cls._split_sentences(text)

        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 5:
                continue
            if any(re.match(p, sent) for p in cls.SKIP_PATTERNS):
                continue

            # 匹配断言模式
            matched = False
            for pattern, claim_type in cls.ASSERTION_PATTERNS:
                m = re.search(pattern, sent)
                if m:
                    # 提取实体
                    entities = cls._extract_entities(sent)
                    claims.append(FactualClaim(
                        text=sent,
                        entities=entities,
                        is_verifiable=(claim_type != "absolute_claim"
                                       or len(entities) > 0),
                        confidence=0.7 if claim_type == "absolute_claim" else 0.5,
                    ))
                    matched = True
                    break

            # 未匹配到已知模式但有实体 → 仍可能是可核查的
            if not matched:
                entities = cls._extract_entities(sent)
                if entities:
                    claims.append(FactualClaim(
                        text=sent,
                        entities=entities,
                        is_verifiable=True,
                        confidence=0.5,
                    ))

        return claims

    # Markdown 格式片段（不应作为独立断言）
    _MARKDOWN_FRAGMENT_RE = re.compile(
        r'^\s*(?:\*\*|__|#{1,6}\s|[-*+]\s|>\s|\d+\.\s|'
        r'\*\*[^*]+\*\*\s*[:：]?\s*)$')
    
    # 过短/纯格式片段（< 12 有效字符）
    _NOISE_FRAGMENT_RE = re.compile(r'^\s*[^\w\u4e00-\u9fff]*\s*$')

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """智能分句：过滤 Markdown 格式噪声和纯符号片段，保留完整断言"""
        raw = re.split(r'[。！？\n;；]', text)
        cleaned = []
        for s in raw:
            s = s.strip()
            if not s or len(s) < 4:
                continue
            if FactExtractor._MARKDOWN_FRAGMENT_RE.match(s):
                continue
            if FactExtractor._NOISE_FRAGMENT_RE.match(s):
                continue
            cleaned.append(s)
        return cleaned

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """提取可能的实体关键词"""
        entities = []
        # 匹配中文专有名词：书名号内容、引号内容、特定词
        for m in re.finditer(r'[《「](.+?)[》」]', text):
            entities.append(m.group(1))
        # 匹配连续汉字/字母（>=2）
        for m in re.finditer(r'[A-Za-z\u4e00-\u9fff]{3,}', text):
            word = m.group()
            if word not in entities:
                entities.append(word)
        return entities[:5]


# ============================================================
# 锚定引擎
# ============================================================
class AnchorEngine:
    """多源锚定：本地知识库 + 可选的 Web 搜索"""

    def __init__(self, enable_web: bool = False, enable_feedback: bool = True,
                 enable_graph: bool = True, enable_deepseek: bool = False):
        self.enable_web = enable_web
        self.enable_feedback = enable_feedback
        self.enable_graph = enable_graph
        self.enable_deepseek = enable_deepseek
        self._graph_reasoner = None  # 惰性加载
        self._weight_learner = None
        self._enable_meta_weights = True
        self._voter = None
        self._vote_mode = "weighted"
        self.headers = {
            "User-Agent": "HallucinationDetector/1.0 (research tool)",
        }
        if self.enable_feedback:
            try:
                import feedback_store
                self.feedback = feedback_store
            except ImportError:
                self.enable_feedback = False


    def _get_kb_years_for_entity(self, claim_text: str) -> list[str]:
        """从KB中提取与claim相关实体的所有年份事实"""
        facts_with_years = []
        for key, entry in KNOWLEDGE_BASE.items():
            # 允许单字键 (如秦/汉/唐) 匹配 2+字词 (如秦朝/汉代/唐朝)
            if key in claim_text or (len(key) == 1 and any(key in w for w in claim_text.split())):
                for fact in entry.get('facts', []):
                    if re.search(r'\d{3,4}', fact):
                        facts_with_years.append(fact)
                break
        return facts_with_years

    def _get_graph_reasoner(self):
        """惰性加载知识图谱推理器"""
        if self._graph_reasoner is None and self.enable_graph:
            try:
                from knowledge_graph import get_reasoner
                self._graph_reasoner = get_reasoner()
            except ImportError:
                self.enable_graph = False
        return self._graph_reasoner

    def _get_weight_learner(self):
        """惰性加载元权重学习器"""
        if self._weight_learner is None and self._enable_meta_weights:
            try:
                from meta_weight_learner import MetaWeightLearner
                self._weight_learner = MetaWeightLearner()
                from checker_registry import Checker
                import checker_classes
                for cls in Checker.registry:
                    self._weight_learner.register_checker(
                        cls.__name__, getattr(cls, 'weight', 1.0))
            except ImportError:
                self._enable_meta_weights = False
        return self._weight_learner

    def _get_voter(self):
        """惰性加载共识投票器"""
        if self._voter is None:
            from consensus_voter import ConsensusVoter, VoteMode
            mode_map = {"majority": VoteMode.MAJORITY,
                        "weighted": VoteMode.WEIGHTED,
                        "borda": VoteMode.BORDA}
            self._voter = ConsensusVoter(
                mode=mode_map.get(self._vote_mode, VoteMode.WEIGHTED))
        return self._voter

    def set_vote_mode(self, mode: str):
        """切换投票模式: majority / weighted / borda"""
        self._vote_mode = mode
        self._voter = None

    def _hybrid_retrieve(self, claim_text: str) -> Optional[VerificationResult]:
        """混合检索：BM25 + TF-IDF 向量匹配，命中后走责任链核查"""
        try:
            from vector_kb import get_hybrid_retriever
            hr = get_hybrid_retriever()
            matches = hr.search(claim_text, top_k=2, threshold=0.12)
            for vk_key, vk_fact, vk_sim in matches:
                claim_kw = [claim_text[i:i+2] for i in range(len(claim_text)-1)]
                if claim_kw:
                    overlap = sum(1 for kw in claim_kw if kw in vk_fact)
                    if overlap == 0:
                        continue
                result = self._compare_with_fact(claim_text, vk_fact)
                if result[0] != "uncertain":
                    return VerificationResult(
                        claim=claim_text,
                        verdict=result[0],
                        confidence=max(result[1], vk_sim * 0.8),
                        evidence=vk_fact,
                        source=f"混合检索 (key={vk_key}, score={vk_sim:.2f})",
                        anchor_type="hybrid_retrieval",
                    )
        except ImportError:
            pass
        return None

    def _web_verify(self, claim_text: str) -> Optional[VerificationResult]:
        """联网多源交叉验证：DuckDuckGo + Wikipedia 加权融合"""
        if not self.enable_web:
            return None
        web_sources = []
        try:
            from web_verifier import WebVerifier
            ddg = WebVerifier()
            web_sources.append(ddg.verify(claim_text))
        except (ImportError, Exception):
            pass
        try:
            from web_verifier import WikipediaVerifier
            wiki = WikipediaVerifier()
            web_sources.append(wiki.verify(claim_text))
        except (ImportError, Exception):
            pass
        verified_sources = [s for s in web_sources if s["verdict"] == "verified"]
        if verified_sources:
            best = max(verified_sources, key=lambda s: s["confidence"])
            return VerificationResult(
                claim=claim_text,
                verdict="verified",
                confidence=best["confidence"] * (0.7 + 0.15 * len(verified_sources)),
                evidence=best["evidence"],
                source=f"{best['source']} (+{len(verified_sources)-1}源交叉验证)" if len(verified_sources) > 1 else best["source"],
                anchor_type="web_search",
            )
        uncertain_sources = [s for s in web_sources if s["verdict"] == "uncertain" and s["confidence"] > 0.1]
        if uncertain_sources:
            best_uncertain = max(uncertain_sources, key=lambda s: s["confidence"])
            if best_uncertain["evidence"]:
                return VerificationResult(
                    claim=claim_text,
                    verdict="uncertain",
                    confidence=best_uncertain["confidence"],
                    evidence=best_uncertain["evidence"],
                    source=best_uncertain["source"],
                    anchor_type="web_search",
                )
        return None

    def _record_uncertain_sample(self, claim_text: str) -> None:
        """将核查未命中的样本写入反馈数据库供后续分析"""
        try:
            import sqlite3, time
            from pathlib import Path
            db_path = Path(__file__).parent / "feedback.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "INSERT INTO uncertain_samples (claim, verdict, confidence, context, created_at) VALUES (?,?,?,?,?)",
                (claim_text[:200], "uncertain", 0.3, "三级管道均未命中", time.time())
            )
            conn.commit()
            conn.close()
        except (sqlite3.Error, OSError, ValueError) as e:
            log.debug("failed to record uncertain sample", error=str(e)[:60])

    def verify(self, claim: FactualClaim) -> VerificationResult:
        """综合核查一条断言"""
        # -1. Markdown/格式化清洗: 去掉 **bold**、`code`、# heading
        import re as _re
        raw = claim.text
        raw = _re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', raw)  # **text** or *text* → text
        raw = _re.sub(r'`([^`]+)`', r'\1', raw)               # `code` → code
        raw = _re.sub(r'^#{1,6}\s+', '', raw)                  # ### heading
        raw = _re.sub(r'^[-*]\s+', '', raw)                    # - list item
        raw = _re.sub(r'\s{2,}', ' ', raw).strip()
        if raw != claim.text:
            claim = FactualClaim(text=raw, entities=claim.entities,
                                 is_verifiable=claim.is_verifiable,
                                 confidence=claim.confidence)
        # 0. 双否定归一化预处理
        normalized_text = self._normalize_double_negation(claim.text)
        if normalized_text != claim.text:
            # 用归一化后的文本创建新 claim 重新走完整流程
            normalized_claim = FactualClaim(
                text=normalized_text,
                entities=claim.entities,
                is_verifiable=claim.is_verifiable,
                confidence=claim.confidence,
            )
            # 递归调用（最多一层，避免无限循环）
            result = self.verify(normalized_claim)
            # 在 evidence 中记录归一化信息
            result.evidence = f"[双否定归一化: {claim.text} → {normalized_text}] {result.evidence}"
            return result

        # 1. 本地知识库
        kb_result = self._check_knowledge_base(claim)
        if kb_result["verdict"] != "uncertain":
            # 如果 KB 置信度低且启用了 DeepSeek，让 DeepSeek 复核
            if self.enable_deepseek and kb_result["confidence"] < 0.85:
                try:
                    from deepseek_verifier import verify_claim
                    ds_result = verify_claim(claim.text)
                    if ds_result["verdict"] != "uncertain":
                        return VerificationResult(
                            claim=claim.text,
                            verdict=ds_result["verdict"],
                            confidence=ds_result["confidence"],
                            evidence=ds_result.get("evidence", ""),
                            source="deepseek",
                            anchor_type="deepseek",
                        )
                except Exception:
                    pass
            return VerificationResult(
                claim=claim.text,
                verdict=kb_result["verdict"],
                confidence=kb_result["confidence"],
                evidence=kb_result["evidence"],
                source=kb_result["source"],
                anchor_type="knowledge_base",
            )
        # 2. DeepSeek 事实核查兜底（当 KB 无法验证时）
        if self.enable_deepseek:
            try:
                from deepseek_verifier import verify_claim
                ds_result = verify_claim(claim.text)
                if ds_result["verdict"] != "uncertain":
                    return VerificationResult(
                        claim=claim.text,
                        verdict=ds_result["verdict"],
                        confidence=ds_result["confidence"],
                        evidence=ds_result.get("evidence", ""),
                        source="deepseek",
                        anchor_type="deepseek",
                    )
            except Exception:
                pass  # DeepSeek 失败时静默降级

        # 3. 混合检索：BM25 + TF-IDF 向量
        #    快速通道：enable_web=False 时跳过向量检索（KB 已是最佳信源）
        if not self.enable_web:
            return VerificationResult(
                claim=claim.text,
                verdict="unverifiable",
                confidence=0.3,
                evidence="无法在本地知识库中验证此信息",
                source="",
                anchor_type="fallback",
            )
        hybrid_result = self._hybrid_retrieve(claim.text)
        if hybrid_result:
            return hybrid_result

        # 3. 联网验证 — 多源交叉验证
        web_result = self._web_verify(claim.text)
        if web_result:
            return web_result

        # 4. 绝对化断言检测
        abs_result = self._check_absolute_claim(claim)
        if abs_result:
            return abs_result
        # 记录不确定样本到反馈库
        self._record_uncertain_sample(claim.text)

        # 5. 无法核查
        return VerificationResult(
            claim=claim.text,
            verdict="unverifiable",
            confidence=0.3,
            evidence="无法在本地知识库和网络中验证此信息",
            source="",
            anchor_type="none",
        )

    # 中文双否定模式 → 归一化为肯定
    _DOUBLE_NEG_PATTERNS = [
        (re.compile(r'不是(?:没有|没)(.+)'), r'\1'),           # 不是没有X → X
        (re.compile(r'不是.{0,6}?(?:没有|没)(.+)'), r'\1'),   # 不是...没有X → X
        (re.compile(r'不能说(?:没有|没)(.+)'), r'\1'),         # 不能说没有X → X
        (re.compile(r'不能说.{0,6}?(?:没有|没)(.+)'), r'\1'), # 不能说...没有X → X
        (re.compile(r'并非(?:没有|没)(.+)'), r'\1'),           # 并非没有X → X
        (re.compile(r'并非.{0,6}?(?:没有|没)(.+)'), r'\1'),   # 并非...没有X → X
        (re.compile(r'并非不(.+)'), r'\1'),                    # 并非不X → X
        (re.compile(r'没有不(.+)'), r'\1'),                    # 没有不X → X
        (re.compile(r'不至于不(.+)'), r'\1'),                  # 不至于不X → X
    ]

    def _normalize_double_negation(self, text: str) -> str:
        """预处理：中文双否定归一化为肯定形式"""
        if self._TRIPLE_NEG_RE.search(text):
            return text
        normalized = text
        for pattern, replacement in self._DOUBLE_NEG_PATTERNS:
            prev = normalized
            normalized = pattern.sub(replacement, normalized)
            if normalized != prev and len(normalized) < len(prev) * 0.3:
                # 归一化后文本过短 → 可能误删，回退
                normalized = prev
        normalized = re.sub(r'\s{2,}', ' ', normalized)
        return normalized.strip()

    # 三重否定 → 无法安全归一化，保留原文
    _TRIPLE_NEG_RE = re.compile(
        r'(?:并非|不是).{0,10}?(?:没有|不|否认).{0,10}?(?:没有|不|否认)')

    def _normalize_double_negation(self, text: str) -> str:
        """预处理：中文双否定归一化为肯定形式

        "毕昇不是没有发明活字印刷术" → "毕昇发明活字印刷术"
        "不能说朱元璋没有建立明朝" → "朱元璋建立明朝"
        三重否定不处理（无法安全归一化）
        """
        # 三重否定 → 跳过
        if self._TRIPLE_NEG_RE.search(text):
            return text

        normalized = text
        for pattern, replacement in self._DOUBLE_NEG_PATTERNS:
            normalized = pattern.sub(replacement, normalized)

        # 清理残留的连接词
        normalized = re.sub(r'\s{2,}', ' ', normalized)
        return normalized.strip()

    def _expand_synonyms(self, text: str) -> str:
        """卫语句: 同义词扩展 — 单层, 立即返回"""
        expanded = text
        for syn, target in SYNONYM_MAP.items():
            if syn in text:
                expanded += " " + target
        return expanded

    # 单字KB键的误匹配过滤：这些常见词含有关键字但语义无关
    _SINGLE_CHAR_FALSE_WORDS = {
        "明": ["发明", "说明", "证明", "聪明", "明确", "表明", "声明", "文明", "透明"],
        "元": ["状元", "元素", "公元", "日元", "单元", "美元", "欧元"],
        "清": ["清楚", "清洁", "清单", "分清", "清晰", "澄清"],
        "唐": ["荒唐"],
        "汉": ["好汉", "汉字", "汉语", "男子汉", "懒汉", "老汉"],
        "电": ["电话", "电脑", "电视", "电影", "电子", "电器", "闪电"],
        "宋": [], "秦": [], "三国": [], "发明": [], "唯一": [], "第一": [],
    }

    def _key_matches_claim(self, key_lower: str, expanded_text: str, text_lower: str, entities: list[str]) -> bool:
        """卫语句: 判断KB键是否匹配当前断言 — 单层"""
        # 单字键：排除嵌入常见词的情况（如"发明"中的"明"）
        if len(key_lower) == 1 and key_lower in self._SINGLE_CHAR_FALSE_WORDS:
            for fw in self._SINGLE_CHAR_FALSE_WORDS[key_lower]:
                if fw in text_lower:
                    return False
        # 键出现在"在X之前/之后"语境中 → 主语不是X，不匹配
        # 例如"在瓦特之前，纽科门发明了蒸汽机" → 说的是纽科门，不是瓦特
        if re.search(r'在' + re.escape(key_lower) + r'(?:之前|之后|以前|以后)', text_lower):
            return False
        return (key_lower in expanded_text 
                or any(key_lower in e.lower() for e in entities)
                or (len(key_lower) >= 2 and all(c in text_lower for c in key_lower)))

    def _check_facts_against_entry(self, claim_text: str, entry: dict) -> dict:
        """检查条目所有事实 — 收集全部结果取最优（高置信度矛盾优先于低置信度验证）"""
        # 兼容 'fact'(单数) 和 'facts'(复数) 两种格式
        facts = entry.get("facts", [entry.get("fact", "")] if "fact" in entry else [])
        if not facts:
            return {"verdict": "uncertain", "confidence": 0.5, "evidence": "", "source": entry.get("source", "")}
        best_result = None
        # 按语义相关度排序: 与claim重叠度高的fact优先检查
        def _fact_relevance(f):
            c_set = set(claim_text)
            f_set = set(f)
            return len(c_set & f_set) / max(1, len(f_set))
        facts = sorted(facts, key=_fact_relevance, reverse=True)
        for fact in facts:
            v, c = self._compare_with_fact(claim_text, fact)
            if v == "uncertain":
                continue
            if best_result is None:
                best_result = {"verdict": v, "confidence": c, "evidence": fact, "source": entry["source"]}
                continue
            # 矛盾仅在以下情况覆盖已验证：
            # 1. 已验证的置信度 < 0.75（弱匹配）
            # 2. 矛盾证据与声明有实质关键词重叠
            if v == "contradicted":
                should_override = False
                if best_result["verdict"] == "verified":
                    # 已验证结果只被高度相关的矛盾覆盖
                    claim_words = set(claim_text)
                    fact_words = set(fact)
                    overlap = len(claim_words & fact_words) / max(1, len(claim_words))
                    if overlap >= 0.5 and c > best_result["confidence"] + 0.1:
                        should_override = True
                elif best_result["verdict"] != "contradicted":
                    should_override = True
                elif c > best_result["confidence"]:
                    should_override = True
                if should_override:
                    best_result = {"verdict": v, "confidence": c, "evidence": fact, "source": entry["source"]}
            elif v == "verified" and best_result["verdict"] != "contradicted":
                if c > best_result["confidence"]:
                    best_result = {"verdict": v, "confidence": c, "evidence": fact, "source": entry["source"]}
        if best_result:
            self._record_feedback(claim_text, best_result["evidence"], best_result)
            return best_result
        result = {"verdict": "uncertain", "confidence": 0.5, "evidence": f"相关: {facts[0][:80]}", "source": entry.get("source", "")}
        self._record_feedback(claim_text, facts[0], result)
        return result

    # ── 语义规范化层 ──────────────────────────
    _CN_NUM_MAP = {
        '零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '百': 100, '千': 1000, '万': 10000, '亿': 100000000,
    }

    @staticmethod
    def _cn_to_int(cn: str) -> int:
        """中文数字→整数 (简化)"""
        if cn == '几':
            return None  # 模糊量词，不转换
        result = 0
        current = 0
        for ch in cn:
            if ch in AnchorEngine._CN_NUM_MAP:
                val = AnchorEngine._CN_NUM_MAP[ch]
                if val >= 10:
                    current = max(current, 1) * val
                    result += current
                    current = 0
                else:
                    current = val
            else:
                return None
        return result + current if result + current > 0 else None


    def _extract_anchor_entity(self, text: str) -> Optional[str]:
        """从文本中提取首次出现的知识库实体作为锚点"""
        text_lower = text.lower()
        for key in sorted(KNOWLEDGE_BASE.keys(), key=len, reverse=True):
            if len(key) >= 1 and key in text:
                if len(key) == 1:
                    if key in text:
                        return key
                else:
                    return key
        return None
    def _normalize_claim(self, text: str) -> list[str]:
        """将叙事性声明分解为原子子句并规范化数字"""
        # 1. 规范化中文数字
        def repl_num(m):
            cn = m.group(1)
            unit = m.group(2) if m.group(2) else ''
            val = self._cn_to_int(cn)
            if val is None:
                return m.group(0)
            return f'{val}{unit}'
        text = re.sub(r'([零一二两三四五六七八九十百千万亿]+)(年|岁|米|公里|个|天|次)?', repl_num, text)
        
        # 2. 提取文本中首次出现的KB实体作为锚点
        anchor_entity = self._extract_anchor_entity(text)
        
        # 3. 分解为子句（先清除数字中的千分位逗号避免误拆）
        _no_num_comma = re.sub(r'(?<=\d),(?=\d)', '', text)
        parts = re.split(r'[，,、。！？；;]', _no_num_comma)
        sub_claims = []
        for part in parts:
            part = part.strip()
            if len(part) >= 4:
                sub_claims.append(part)
        
        # 如果只有一个子句，按连接词拆分
        if len(sub_claims) <= 1:
            parts2 = re.split(r'(?:其实|所以|因为|而且|但是|不过|因此|于是|然后)', text)
            sub_claims = [p.strip() for p in parts2 if len(p.strip()) >= 4]
        
        # 4. 回贴锚点实体到缺失的子句
        if anchor_entity and len(sub_claims) > 1:
            fixed = []
            for sc in sub_claims:
                if anchor_entity not in sc:
                    fixed.append(f'{anchor_entity}{sc}')
                else:
                    fixed.append(sc)
            sub_claims = fixed
        
        return sub_claims if sub_claims else [text]

    def _match_sub_claims(self, sub_claims: list, claim_entities: list) -> Optional[dict]:
        """逐子句匹配知识库并聚合结果，矛盾优先返回"""
        sub_results = []
        for sub in sub_claims:
            sub_expanded = self._expand_synonyms(sub.lower())
            for key in sorted(KNOWLEDGE_BASE.keys(), key=len, reverse=True):
                if not self._key_matches_claim(key.lower(), sub_expanded, sub.lower(), claim_entities):
                    continue
                entity_conf = self._entity_match_confidence(key, sub, key.lower())
                if key.lower() in sub_expanded:
                    entity_conf = min(entity_conf + 0.25, 1.0)
                if entity_conf < 0.4:
                    continue
                result = self._check_facts_against_entry(sub, KNOWLEDGE_BASE[key])
                if result["verdict"] != "uncertain":
                    sub_results.append(result)
                    break
        # 聚合子句结果：矛盾优先
        contradicted_results = [r for r in sub_results if r["verdict"] == "contradicted"]
        if contradicted_results:
            return max(contradicted_results, key=lambda r: r["confidence"])
        verified_results = [r for r in sub_results if r["verdict"] == "verified"]
        if verified_results:
            return max(verified_results, key=lambda r: r["confidence"])
        if sub_results:
            return sub_results[0]
        return None

    def _check_knowledge_base(self, claim: FactualClaim) -> dict:
        """在知识库中匹配声明，优先走用户反馈的重映射键，否则按关键词查 KB。"""
        # -1. 叙事标记检测: 含"的传说/的故事/的说法/的迷思" → 不做事实验证
        if re.search(r'(?:的传说|的故事|的说法|的迷思|的神话|的谣言)', claim.text):
            return {
                "verdict": "unverifiable",
                "confidence": 0.30,
                "evidence": "该文本为叙事/传闻引用，非事实断言，不做验证",
                "source": "narrative_filter",
            }
        # 0. 语义规范化：分解为子句并分别尝试匹配
        # 聚合策略：任一子句矛盾 → 整体矛盾；全验证 → 验证；否则不确定
        sub_claims = self._normalize_claim(claim.text)
        if len(sub_claims) > 1:
            aggregated = self._match_sub_claims(sub_claims, claim.entities)
            if aggregated:
                return aggregated
        # 1. 完整声明匹配 (原有逻辑)
        # 优先查重匹配记录：用户指定了正确的KB键
        if self.enable_feedback:
            rematch_key = self.feedback.find_rematch(claim.text)
            if rematch_key and rematch_key in KNOWLEDGE_BASE:
                result = self._check_facts_against_entry(claim.text, KNOWLEDGE_BASE[rematch_key])
                log.debug("rematch hit", key=rematch_key, claim=claim.text[:40])
                return result
        # 正常KB搜索
        expanded = self._expand_synonyms(claim.text.lower())
        for key in sorted(KNOWLEDGE_BASE.keys(), key=len, reverse=True):
            if not self._key_matches_claim(key.lower(), expanded, claim.text.lower(), claim.entities):
                continue
            # 实体类型验证：跳过类型严重不匹配的 KB 条目
            entity_conf = self._entity_match_confidence(key, claim.text, key.lower())
            # 同义词扩展匹配加成：KB键已在扩展文本中 → 提高置信度
            if key.lower() in expanded:
                entity_conf = min(entity_conf + 0.25, 1.0)
            if entity_conf < 0.4:
                continue
            result = self._check_facts_against_entry(claim.text, KNOWLEDGE_BASE[key])
            if result["verdict"] != "uncertain":
                return result
            # uncertain → 继续尝试下一个 key
        return self._semantic_match_kb(claim)
    def _compute_similarity(self, text: str, key: str) -> float:
        """多粒度n-gram Jaccard + 字符重叠相似度"""
        # 提取1~3-gram（uni+bi+tri gram）
        def ngrams(s, n):
            return {s[i:i+n] for i in range(len(s)-n+1)}
        
        text_ngrams = set()
        key_ngrams = set()
        for n in (1, 2, 3):
            text_ngrams |= ngrams(text, n)
            key_ngrams |= ngrams(key, n)
        
        char_overlap = len(set(key) & set(text)) / max(len(set(key)), 1)
        
        if not key_ngrams and not text_ngrams:
            return char_overlap * 0.8
        if not key_ngrams:
            return char_overlap * 0.7
        if not text_ngrams:
            return char_overlap * 0.4
        
        ngram_score = len(text_ngrams & key_ngrams) / max(len(text_ngrams | key_ngrams), 1)
        # n-gram权重高于字符重叠（n-gram捕捉语序信息）
        return ngram_score * 0.65 + char_overlap * 0.35

    # ── 实体类型推断与置信度 ──────────────────────────

    # 实体类型推断正则模式
    _PERSON_PATTERNS = [
        re.compile(r'(出生于?|生于|逝于|卒于|去世于)\s*\d'),
        re.compile(r'是.{0,4}(人|科学家|文学家|音乐家|哲学家|画家|诗人|作家|数学家|物理学家|化学家|生物学家|发明家|军事家|政治家|皇帝|总统|总理|国王|丞相)'),
        re.compile(r'(发明了?|发现了?|提出了?|创立了?|创作了?|发表了?|获得了?)'),
        re.compile(r'(的(?:学生|老师|父亲|母亲|儿子|女儿|朋友|对手))'),
    ]
    _PLACE_PATTERNS = [
        re.compile(r'(位于|坐落于|地处|在.{0,4}(?:省|市|县|国|洲|地区|边境))'),
        re.compile(r'(首都是?|都城.{0,2}[是为])'),
        re.compile(r'(建于?|建造于?|始建于?|落成于?)\s*\d'),
        re.compile(r'(是.{0,4}(?:城市|国家|首都|建筑|宫殿|寺庙|山峰|河流|海洋|沙漠|森林))'),
    ]
    _EVENT_PATTERNS = [
        re.compile(r'(爆发于?|发生于?|始于?|结束于?|持续了?)\s*\d'),
        re.compile(r'(是.{0,4}(?:战争|革命|运动|事件|灾难|发现|发明|会议|奥运会))'),
        re.compile(r'(导火索|标志.{0,2}是|拉开.{0,2}序幕)'),
    ]
    _ORG_PATTERNS = [
        re.compile(r'(公司|企业|集团|组织|机构|协会|委员会|基金会)'),
        re.compile(r'(成立于?|注册于?)\s*\d'),
    ]

    def _infer_entity_type(self, text: str, entity_name: str) -> tuple:
        """从文本上下文推断实体类型，返回 (type, confidence)
        类型: person / place / event / organization / concept / unknown"""
        idx = text.lower().find(entity_name.lower())
        if idx < 0:
            return ("unknown", 0.0)
        start = max(0, idx - 30)
        end = min(len(text), idx + len(entity_name) + 30)
        context = text[start:end]

        scores = {}
        for pat in self._PERSON_PATTERNS:
            if pat.search(context):
                scores["person"] = scores.get("person", 0) + 1
        for pat in self._PLACE_PATTERNS:
            if pat.search(context):
                scores["place"] = scores.get("place", 0) + 1
        for pat in self._EVENT_PATTERNS:
            if pat.search(context):
                scores["event"] = scores.get("event", 0) + 1
        for pat in self._ORG_PATTERNS:
            if pat.search(context):
                scores["organization"] = scores.get("organization", 0) + 1

        if not scores:
            if len(entity_name) <= 2:
                return ("concept", 0.3)
            return ("unknown", 0.2)

        best_type = max(scores, key=scores.get)
        best_count = scores[best_type]
        total = sum(scores.values())
        confidence = min(best_count / max(total, 1), 0.85)
        return (best_type, confidence)

    def _kb_entry_type(self, key: str, entry: dict) -> str:
        """从 KB 条目推断类型"""
        source = entry.get("source", "")
        facts = entry.get("facts", [])
        all_text = f"{key} {' '.join(facts[:3])}"

        source_type_map = {
            "史记": "event", "汉书": "event", "旧唐书": "event", "资治通鉴": "event",
        }
        if source in source_type_map:
            return source_type_map[source]

        inferred, _ = self._infer_entity_type(all_text, key)
        if inferred != "unknown":
            return inferred

        if any(w in all_text for w in ["位于", "建于", "首都", "城市", "山峰", "河流"]):
            return "place"
        if any(w in all_text for w in ["出生于", "发明", "提出", "创作"]):
            return "person"
        if any(w in all_text for w in ["爆发", "战争", "革命", "运动", "始于"]):
            return "event"

        return "concept"

    def _entity_match_confidence(self, kb_key: str, text: str, kb_key_lower: str) -> float:
        """计算 KB 键与文本中实体的匹配置信度，综合文本相似度 + 类型兼容性"""
        text_lower = text.lower()
        exact_match = kb_key_lower in text_lower

        text_type, text_type_conf = self._infer_entity_type(text, kb_key)
        entry = KNOWLEDGE_BASE.get(kb_key, {})
        kb_type = self._kb_entry_type(kb_key, entry)

        type_compat = self._type_compatibility(text_type, kb_type)

        base = 0.6 if exact_match else 0.3
        type_weight = 0.4
        score = base + type_weight * type_compat * text_type_conf
        return min(score, 1.0)

    @staticmethod
    def _type_compatibility(text_type: str, kb_type: str) -> float:
        """两个实体类型的兼容性评分"""
        if text_type == kb_type:
            return 1.0
        if text_type == "unknown" or kb_type == "unknown":
            return 0.6
        if text_type == "concept" or kb_type == "concept":
            return 0.5
        incompat_pairs = [("person", "place"), ("person", "event"), ("place", "event")]
        if (text_type, kb_type) in incompat_pairs or (kb_type, text_type) in incompat_pairs:
            return 0.2
        return 0.4

    def _find_best_match(self, text_lower: str) -> tuple:
        """找到最相似的KB条目 — 多粒度 + 关键词权重提升"""
        best_score, best_key, best_entry = 0, None, None
        # 提取文本中的关键词（2字以上的实词）
        keywords = re.findall(r'[\u4e00-\u9fff\w]{2,}', text_lower)
        
        for key, entry in KNOWLEDGE_BASE.items():
            key_lower = key.lower()
            score = self._compute_similarity(text_lower, key_lower)
            # 关键词精确命中加成：如果KB键作为完整词出现在文本中
            if key_lower in keywords:
                score = min(score + 0.15, 1.0)
            # 文本中的关键词与KB键精确匹配时额外加分
            for kw in keywords:
                if kw == key_lower:
                    score = min(score + 0.2, 1.0)
                    break
            # 实体类型匹配置信度加权 — 修复死代码
            entity_conf = self._entity_match_confidence(key, text_lower, key_lower)
            score = score * (0.7 + 0.3 * entity_conf)
            # 位置加分: KB键出现在文本前1/3处 → 更可能是主题
            key_pos = text_lower.find(key_lower)
            if key_pos >= 0 and key_pos < len(text_lower) / 3:
                score = min(score * 1.1, 1.0)
            if score > best_score:
                best_score, best_key, best_entry = score, key, entry
        return best_score, best_key, best_entry

    # 通用规则条目：这些KB键本身是抽象规则而非具体事实
    # 语义匹配时需要更高阈值，避免误匹配到叙事性claim
    _GENERIC_KEYS = {"发明", "唯一", "第一"}

    def _semantic_match_kb(self, claim: FactualClaim) -> dict:
        """语义回退匹配 — 多粒度相似度 + 嵌入检索兜底"""
        text_lower = claim.text.lower()
        best_score, best_key, best_entry = self._find_best_match(text_lower)
        
        # 自适应阈值：文本越长，阈值越低（长文本信息更多）
        text_len = len(text_lower)
        if text_len < 10:
            threshold = 0.18
        elif text_len < 30:
            threshold = 0.15
        else:
            threshold = 0.12
        
        # 通用规则条目需要更高阈值（避免"故事/传说"语境误匹配）
        if best_key in self._GENERIC_KEYS:
            threshold = max(threshold, 0.40)
            if best_key:
                entity_conf = self._entity_match_confidence(best_key, text_lower, best_key.lower())
                if entity_conf < 0.5:
                    threshold = max(threshold, 0.35)
                elif entity_conf < 0.7:
                    threshold = max(threshold, 0.22)
        
        if best_score < threshold:
            # 嵌入检索兜底 — 当传统匹配失败时
            try:
                searcher = _get_embedding_searcher()
                emb_results = searcher.search(text_lower, top_k=3, min_score=0.15)
                if emb_results:
                    best_key, best_score = emb_results[0]
                    best_entry = KNOWLEDGE_BASE.get(best_key)
                    if best_entry:
                        result = self._check_facts_against_entry(claim.text, best_entry)
                        if result["verdict"] != "uncertain":
                            result["semantic_match"] = {"key": best_key, "score": round(best_score, 3), "method": "embedding"}
                            return result
            except Exception:
                pass  # 嵌入检索失败时静默回退
            return {"verdict": "uncertain", "confidence": 0, "evidence": "", "source": ""}
        
        result = self._check_facts_against_entry(claim.text, best_entry)
        result["semantic_match"] = {"key": best_key, "score": round(best_score, 3)}
        return result

    def _weighted_decide(self, results: list) -> tuple:
        """加权决策：计算幻觉分数，按高权重优先/最高加权分返回最终裁决

        支持通过 set_vote_mode() 切换共识投票模式 (majority/weighted/borda)
        """
        self._last_vote_details = {
            "votes": [{"checker": n, "verdict": v, "confidence": c,
                       "weight": w, "weighted_score": round(ws, 3)}
                      for n, v, c, w, ws in results],
        }
        total_w = sum(r[3] for r in results)
        hallucination_sum = 0.0
        for n, v, c, w, ws in results:
            if v == "contradicted":
                hallucination_sum += w * c
            elif v == "uncertain":
                hallucination_sum += w * c * 0.5
        self._last_vote_details["hallucination_score"] = round(
            hallucination_sum / max(total_w, 0.001), 3)

        # 共识投票模式（可选：通过 set_vote_mode 切换）
        if self._vote_mode != "weighted":
            try:
                voter = self._get_voter()
                verdict, confidence, vote_info = voter.vote(results)
                self._last_vote_details["decision"] = "consensus"
                self._last_vote_details["vote_mode"] = vote_info.get("mode", self._vote_mode)
                self._last_vote_details["vote_detail"] = vote_info
                return (verdict, confidence)
            except Exception:
                pass  # 回退到默认逻辑

        # 默认加权决策（保留原逻辑，兼容现有测试）
        self._last_vote_details["vote_mode"] = "weighted"
        high_weight = [(n, v, c, w, ws) for n, v, c, w, ws in results if w >= 0.85]
        if high_weight:
            best = max(high_weight, key=lambda x: x[4])
            self._last_vote_details["decision"] = best[0]
            return (best[1], best[2])
        best = max(results, key=lambda x: x[4])
        self._last_vote_details["decision"] = best[0]
        if best[1] == "contradicted" and best[2] < 0.65:
            return ("uncertain", 0.5)
        return (best[1], best[2])

    def _compare_with_fact(self, claim: str, fact: str) -> tuple:
        """反馈优先 + 加权责任链: 先查自进化库 → 收集所有检查器结果 → 加权最优"""
        # 第零层: 自我验证 + 高相似度快速通道
        claim_norm = re.sub(r'(?<=\d),(?=\d)', '', claim.strip())  # 去千分位逗号
        fact_norm = re.sub(r'(?<=\d),(?=\d)', '', fact.strip())
        if claim_norm == fact_norm:
            return ("verified", 0.95)

        # 高相似度快速通道: 字符重叠率 > 85% → 判 verified
        # 处理同一事实的不同表述（如"最新高度8848.86米" vs "2020年测量8848.86米"）
        # 数字一致性守卫: 双方都有数字但数字集合不同时，跳过快速通道
        # 防止字符高度重叠但数字冲突被误判为 verified（如 1989 vs 1991）
        _digit_conflict = False
        _claim_digits = set(re.findall(r'\d+', claim_norm))
        _fact_digits = set(re.findall(r'\d+', fact_norm))
        if _claim_digits and _fact_digits and _claim_digits != _fact_digits:
            _digit_conflict = True

        # 否定冲突守卫：一方有否定词另一方无 → 跳过快速通道
        _claim_has_neg = bool(re.search(r'不是|没有|并非|不在|不会|不可能|错误', claim_norm))
        _fact_has_neg = bool(re.search(r'不是|没有|并非|不在|不会|不可能|错误', fact_norm))
        _neg_conflict = _claim_has_neg != _fact_has_neg

        claim_set = set(claim_norm)
        fact_set = set(fact_norm)
        # 实体名称冲突守卫：双方提到不同人名/地名时跳过快速通道
        _cn_names_c = set(re.findall(r'[一-鿿]{2,3}(?=是|发明|建立|提出|发现)', claim_norm))
        _cn_names_f = set(re.findall(r'[一-鿿]{2,3}(?=是|发明|建立|提出|发现)', fact_norm))
        _name_conflict = bool(_cn_names_c and _cn_names_f and _cn_names_c != _cn_names_f)
        if claim_set and fact_set and not _digit_conflict and not _neg_conflict and not _name_conflict:
            overlap = len(claim_set & fact_set) / max(len(claim_set), len(fact_set))
            if overlap > 0.85:
                return ("verified", 0.92)
        # 第一层: 查询自进化反馈库
        if self.enable_feedback:
            record = self.feedback.find_applied_correction(claim, fact)
            if record:
                log.debug("feedback hit", claim=claim[:40])
                return (record["verdict"], record["confidence"])
        # 第二层: 责任链检查器 — 收集所有结果后加权决策
        results = []  # [(checker_name, verdict, confidence, weight)]
        for checker_cls in Checker.registry:
            checker_inst = checker_cls()
            learner = self._get_weight_learner()
            weight = learner.get_weight(checker_cls.__name__) if learner else getattr(checker_cls, 'weight', 1.0)
            result = checker_inst.check(claim, fact, engine=self)
            if result:
                verdict, confidence = result
                weighted_score = weight * confidence
                results.append((checker_cls.__name__, verdict, confidence, weight, weighted_score))
                log.debug("checker hit", checker=checker_cls.__name__,
                          verdict=verdict, weight=weight, weighted_score=round(weighted_score, 3))
        if not results:
            log.debug("all checkers miss", claim=claim[:40])
            self._last_vote_details = {"votes": [], "hallucination_score": 0.0}
            return ("uncertain", 0.5)
        verdict, confidence = self._weighted_decide(results)
        learner = self._get_weight_learner()
        if learner:
            for name, v, c, w, ws in results:
                is_correct = (v == verdict)
                learner.record(name, v, is_correct, c)
            learner.learn_step()
        return (verdict, confidence)

    def get_vote_details(self) -> dict:
        """返回最近一次 _compare_with_fact 的投票明细和幻觉分数"""
        return getattr(self, '_last_vote_details', {"votes": [], "hallucination_score": 0.0})

    def _record_feedback(self, claim: str, fact: str, result: dict) -> None:
        """记录反馈（跳过已有记录避免重复）"""
        if not self.enable_feedback:
            return
        try:
            existing = self.feedback.find_similar(claim, fact)
            if not existing:
                self.feedback.FeedbackRecord(
                    claim=claim,
                    fact=fact,
                    verdict=result["verdict"],
                    confidence=result["confidence"],
                    evidence=result.get("evidence", ""),
                    source=result.get("source", ""),
                )
                # 插入
                import feedback_store
                feedback_store.insert_record(feedback_store.FeedbackRecord(
                    claim=claim,
                    fact=fact,
                    verdict=result["verdict"],
                    confidence=result["confidence"],
                    evidence=result.get("evidence", ""),
                    source=result.get("source", ""),
                ))
        except (OSError, ValueError, AttributeError):
            pass  # 反馈记录失败不阻塞主流程
        # 飞轮效应：高置信度反馈自动合并到知识库
        if result.get("verdict") == "verified" and result.get("confidence", 0) >= 0.9:
            self._auto_merge_to_kb(claim, result)

    def _auto_merge_to_kb(self, claim: str, result: dict) -> None:
        """飞轮效应：高置信度验证通过后自动合并到用户知识库并热加载"""
        try:
            import json, os
            from pathlib import Path
            kb_user_path = Path(__file__).parent / "kb_user.json"
            # 加载现有用户知识库
            user_kb = {}
            if kb_user_path.exists():
                with open(kb_user_path) as f:
                    user_kb = json.load(f)
            # 生成关键词
            key = claim[:12].strip()
            entry = {
                "category": "auto_merged",
                "fact": result.get("evidence", claim),
                "source": result.get("source", "auto_feedback"),
                "confidence": result.get("confidence", 0.9),
            }
            if key not in user_kb:
                user_kb[key] = entry
                with open(kb_user_path, "w") as f:
                    json.dump(user_kb, f, ensure_ascii=False, indent=2)
                # 热加载到 KNOWLEDGE_BASE
                KNOWLEDGE_BASE[key] = entry
                log.info("auto_merged to KB", key=key, claim=claim[:30])
        except (OSError, ValueError, KeyError) as e:
            log.debug("auto_merge skipped", error=str(e)[:40])

    def _check_absolute_claim(self, claim: FactualClaim) -> Optional[VerificationResult]:
        """检测绝对化断言（"一定""绝对""从来"）"""
        markers = ["一定", "绝对", "从来", "永远", "所有人", "没有人", "毫无疑问"]
        if any(m in claim.text for m in markers):
            return VerificationResult(
                claim=claim.text,
                verdict="uncertain",
                confidence=0.3,
                evidence="包含绝对化表述，此类断言几乎总是过度简化",
                source="逻辑学",
                anchor_type="consistency",
            )
        return None

    # ── Truth Router 集成 ────────────────────────────────

    def retrieval_check(self, claim: str, max_results: int = 10) -> dict:
        """多事实检索校验 — 集成 Truth Router 检索管线

        从 kb_core.json + fact_store.db 检索相关事实，
        逐一比对后聚合得出综合判决。

        返回:
            {
                "verdict": "verified"|"contradicted"|"uncertain",
                "confidence": float,
                "facts_checked": int,
                "entities": [str, ...],
                "checks": [{"fact": str, "verdict": str, "confidence": float}, ...],
                "source": str,  # "entity_map"|"fts"|"kb_core"|"none"
            }
        """
        try:
            from truth_router.retrieval import retrieve
            retrieval = retrieve(claim, max_results)
        except ImportError:
            return {
                "verdict": "uncertain", "confidence": 0.5,
                "facts_checked": 0, "entities": [],
                "checks": [], "source": "import_error"
            }

        facts = retrieval.get('facts', [])
        if not facts:
            return {
                "verdict": "uncertain", "confidence": 0.5,
                "facts_checked": 0,
                "entities": retrieval.get('entities', []),
                "checks": [],
                "source": retrieval.get('source', 'none')
            }

        checks = []
        for f in facts:
            verdict, conf = self._compare_with_fact(claim, f['fact'])
            checks.append({
                "fact": f['fact'],
                "source": f.get('source', ''),
                "verdict": verdict,
                "confidence": round(conf, 4),
            })

        # 聚合判决
        if checks:
            verdict_order = {"verified": 3, "contradicted": 2, "uncertain": 1}
            best = max(checks, key=lambda c: (verdict_order.get(c['verdict'], 0), c['confidence']))
            final_verdict = best['verdict']
            final_confidence = best['confidence']
        else:
            final_verdict = 'uncertain'
            final_confidence = 0.5

        return {
            "verdict": final_verdict,
            "confidence": final_confidence,
            "facts_checked": len(checks),
            "entities": retrieval.get('entities', []),
            "checks": checks,
            "source": retrieval.get('source', 'none'),
        }

    def retrieval_augmented_verify(self, claim_text: str) -> dict:
        """检索增强验证 — verify() 的增强版

        先走标准 verify()，若结果不确定则回退到多事实检索。
        """
        claim = FactualClaim(
            text=claim_text,
            entities=[],
            is_verifiable=True,
            confidence=0.7,
        )
        result = self.verify(claim)

        # 标准验证结果不确定时，走检索增强
        if result.verdict == "uncertain" or result.confidence < 0.6:
            retrieval = self.retrieval_check(claim_text)
            if retrieval['facts_checked'] > 0 and retrieval['confidence'] >= result.confidence:
                result.verdict = retrieval['verdict']
                result.confidence = retrieval['confidence']
                result.evidence = f"检索增强: {retrieval['facts_checked']}条事实校验"
                result.source = retrieval['source']

        return result


# ============================================================
# 报告生成器
# ============================================================

class Reporter:
    """生成可读的幻觉报告"""

    VERDICT_ICONS = {
        "verified": "✅",
        "contradicted": "🔴",
        "uncertain": "🟡",
        "unverifiable": "⬜",
    }

    VERDICT_LABELS = {
        "verified": "已验证",
        "contradicted": "矛盾",
        "uncertain": "不确定",
        "unverifiable": "不可核查",
    }

    @classmethod
    def generate(cls, report: HallucinationReport) -> str:
        lines = []
        lines.append("=" * 62)
        lines.append("  幻觉检测报告")
        lines.append("=" * 62)
        lines.append(f"  输入长度: {len(report.input_text)} 字符")
        lines.append(f"  提取断言: {len(report.claims)} 条")
        lines.append(f"  整体可信度: {report.overall_score:.0%}")
        lines.append(f"  疑似幻觉率: {report.hallucination_ratio:.0%}")
        lines.append("=" * 62)

        if not report.results:
            lines.append("\n  未检测到可核查的断言。")
            return "\n".join(lines)

        lines.append("")
        for i, r in enumerate(report.results, 1):
            icon = cls.VERDICT_ICONS.get(r.verdict, "❓")
            label = cls.VERDICT_LABELS.get(r.verdict, r.verdict)
            lines.append(f"  {icon} [{label}] {r.claim[:80]}")
            if r.evidence:
                lines.append(f"     证据: {r.evidence[:100]}")
            if r.source:
                lines.append(f"     来源: {r.source}")
            if r.verdict != "verified":
                lines.append(f"     可信度: {r.confidence:.0%}")
            lines.append("")

        if report.warnings:
            lines.append("-" * 62)
            lines.append("  ⚠️  警告:")
            for w in report.warnings:
                lines.append(f"     • {w}")

        lines.append("=" * 62)
        return "\n".join(lines)

    @classmethod
    def to_json(cls, report: HallucinationReport) -> str:
        return json.dumps({
            "input_text": report.input_text,
            "num_claims": len(report.claims),
            "overall_score": report.overall_score,
            "hallucination_ratio": report.hallucination_ratio,
            "warnings": report.warnings,
            "results": [
                {
                    "claim": r.claim,
                    "verdict": r.verdict,
                    "confidence": r.confidence,
                    "evidence": r.evidence,
                    "source": r.source,
                    "anchor_type": r.anchor_type,
                }
                for r in report.results
            ],
        }, ensure_ascii=False, indent=2)


# ============================================================
# 主流程
# ============================================================


def _load_config():
    """Load configuration from config.json, return dict or empty dict on failure."""
    config_path = Path(__file__).parent / "config.json"
    try:
        with open(config_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

class HallucinationDetector:
    """Anchor 事实检测器主类"""

    def __init__(self, enable_web: bool = False, enable_deepseek: bool = False):
        self.extractor = FactExtractor()
        self.anchor = AnchorEngine(enable_web=enable_web, enable_deepseek=enable_deepseek)

    def analyze(self, text: str) -> HallucinationReport:
        report = HallucinationReport(input_text=text)

        # 1. 提取断言
        claims = self.extractor.extract(text)
        report.claims = claims

        if not claims:
            report.overall_score = 1.0
            return report

        # 2. 逐条核查
        for claim in claims:
            result = self.anchor.verify(claim)
            report.results.append(result)

        # 3. 计算整体指标
        total = len(report.results)
        contradicted = sum(1 for r in report.results
                          if r.verdict == "contradicted")
        uncertain = sum(1 for r in report.results
                       if r.verdict == "uncertain")
        verified = sum(1 for r in report.results
                      if r.verdict == "verified")

        if total > 0:
            report.hallucination_ratio = contradicted / total
            report.overall_score = 1.0 - (
                contradicted * 0.8 + uncertain * 0.3
            ) / total
            report.overall_score = max(0.0, report.overall_score)

        # 4. 生成警告
        self._generate_warnings(report, contradicted, uncertain)

        # 5. 预测加工可解释性
        prior_strength = sum(1 for r in report.results
                           if r.verdict == "verified") / max(total, 1)
        sensory_precision = sum(r.confidence for r in report.results
                               if r.verdict == "contradicted") / max(contradicted, 1) if contradicted > 0 else 0.0
        report.predictive_processing = {
            "prior_strength": round(prior_strength, 2),
            "sensory_precision": round(sensory_precision, 2),
            "hallucination_probability": round(report.hallucination_ratio, 2),
            "analysis": (
                f"模型的先验强度({prior_strength:.2f})"
                + (f"低于" if sensory_precision > prior_strength else "高于")
                + f"外部事实核查的感官精度({sensory_precision:.2f})，"
                + (f"判定为高幻觉概率。" if report.hallucination_ratio > 0.3
                   else f"判定为中等幻觉概率。" if report.hallucination_ratio > 0.1
                   else f"判定为低幻觉概率。")
            )
        }

        return report

    def _generate_warnings(self, report, contradicted: int, uncertain: int):
        """Generate warnings from verification results."""
        if report.hallucination_ratio > 0:
            report.warnings.append(
                f"发现 {contradicted} 条与已知事实矛盾的断言"
            )
        if uncertain > 0:
            report.warnings.append(
                f"有 {uncertain} 条断言无法验证——建议人工复核"
            )
        # 绝对化表述警告
        abs_count = sum(1 for r in report.results
                       if r.anchor_type == "consistency")
        if abs_count > 0:
            report.warnings.append(
                f"检测到 {abs_count} 条绝对化表述（「一定」「从来」等），"
                "此类断言几乎总是存在例外"
            )


def generate_correction_prompt(text: str) -> str:
    """分析文本，若有事实矛盾则生成纠正性提示，供注入 LLM system prompt。
    返回空字符串表示无需纠正。"""
    detector = HallucinationDetector()
    report = detector.analyze(text)
    corrections = []
    for r in report.results:
        if r.verdict == 'contradicted' and r.evidence:
            corrections.append(
                f"- 用户说「{r.claim}」，但已知事实是：{r.evidence}（来源：{r.source}）"
            )
    if not corrections:
        return ''
    parts = [
        '[觉察层 · 自动事实纠正]',
        '以下用户消息中存在与已知事实矛盾的内容，请在回复中礼貌纠正：',
    ]
    parts.extend(corrections)
    parts.append('纠正时请引用可靠来源，保持礼貌和专业。')
    return chr(10).join(parts)

def main():
    parser = argparse.ArgumentParser(
        description="Anchor 事实检测器 — 检查 LLM 输出中的事实错误",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s "朱元璋发明了火锅"
  %(prog)s --file llm_output.txt
  %(prog)s --json "Python 是1989年发布的" 
  echo "地球是平的" | %(prog)s --stdin
        """,
    )
    parser.add_argument("text", nargs="?", help="要检查的文本")
    parser.add_argument("--file", "-f", help="从文件读取")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    parser.add_argument("--web", action="store_true", help="启用 Web 搜索 (未实现)")
    args = parser.parse_args()

    # 读取输入
    if args.stdin:
        text = sys.stdin.read()
    elif args.file:
        filepath = os.path.realpath(os.path.abspath(args.file))
        cwd = os.path.realpath(os.getcwd())
        if not filepath.startswith(cwd + os.sep) and filepath != cwd:
            print(f"安全拒绝: 路径穿越检测 — {args.file}", file=sys.stderr)
            sys.exit(1)
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        parser.print_help()
        sys.exit(1)

    # 检测
    detector = HallucinationDetector(enable_web=args.web)
    report = detector.analyze(text)

    # 输出
    if args.json:
        print(Reporter.to_json(report))
    else:
        print(Reporter.generate(report))


if __name__ == "__main__":
    main()
# test
