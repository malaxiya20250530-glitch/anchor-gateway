#!/usr/bin/env python3
"""
幻觉检测基准评测 — 内置测试集 + 标准指标

指标:
  Precision (精确率): 标记为幻觉的断言中真正是幻觉的比例
  Recall (召回率):     真实幻觉中被检测出的比例
  F1 Score:            Precision 和 Recall 的调和平均
  Latency (延迟):      平均检测耗时 (ms)
"""

import time
import json
from pathlib import Path
from typing import Optional


# ── 内置评测集 ────────────────────────────────────

# 50 条中英文混合断言，覆盖：
#   常识错误 · 历史谬误 · 科学谬误 · 地理错误 · 正确事实
BENCHMARK_CASES = [
  {
    "claim": "秦朝是中国第一个大一统王朝",
    "expected": "verified",
    "domain": "史记"
  },
  {
    "claim": "秦朝于公元前207年灭亡",
    "expected": "verified",
    "domain": "史记"
  },
  {
    "claim": "汉朝分为西汉(前202-9年)和东汉(25-220年)",
    "expected": "verified",
    "domain": "汉书"
  },
  {
    "claim": "造纸术在西汉时期已有雏形",
    "expected": "verified",
    "domain": "汉书"
  },
  {
    "claim": "唐朝(618-907年)是中国历史上最繁荣的朝代之一",
    "expected": "verified",
    "domain": "旧唐书"
  },
  {
    "claim": "雕版印刷术在唐代发明",
    "expected": "verified",
    "domain": "旧唐书"
  },
  {
    "claim": "北宋(960-1127年)首都是开封",
    "expected": "verified",
    "domain": "宋史"
  },
  {
    "claim": "毕昇于北宋庆历年间发明活字印刷术",
    "expected": "verified",
    "domain": "宋史"
  },
  {
    "claim": "明朝(1368-1644年)由朱元璋建立",
    "expected": "verified",
    "domain": "明史"
  },
  {
    "claim": "郑和七下西洋发生在明代永乐年间",
    "expected": "verified",
    "domain": "明史"
  },
  {
    "claim": "Python 由 Guido van Rossum 于 1991 年首次发布",
    "expected": "verified",
    "domain": "Python.o"
  },
  {
    "claim": "Python 是解释型面向对象的高级编程语言",
    "expected": "verified",
    "domain": "Python.o"
  },
  {
    "claim": "Linux 内核由 Linus Torvalds 于 1991 年创建",
    "expected": "verified",
    "domain": "kernel.o"
  },
  {
    "claim": "Linux 是开源的类 Unix 操作系统内核",
    "expected": "verified",
    "domain": "kernel.o"
  },
  {
    "claim": "HTTP 协议由 Tim Berners-Lee 于 1989 年在 CERN 提出",
    "expected": "verified",
    "domain": "W3C"
  },
  {
    "claim": "HTTP 是超文本传输协议",
    "expected": "verified",
    "domain": "W3C"
  },
  {
    "claim": "Java 由 James Gosling 于 1995 年在 Sun Microsystems 发布",
    "expected": "verified",
    "domain": "Oracle"
  },
  {
    "claim": "Java 最初的名字是 Oak",
    "expected": "verified",
    "domain": "Oracle"
  },
  {
    "claim": "C 语言由 Dennis Ritchie 于 1972 年在贝尔实验室开发",
    "expected": "verified",
    "domain": "计算机科学史"
  },
  {
    "claim": "C 语言是为了写 Unix 而创造的",
    "expected": "verified",
    "domain": "计算机科学史"
  },
  {
    "claim": "JavaScript 由 Brendan Eich 于 1995 年在 Netscape 创建",
    "expected": "verified",
    "domain": "Mozilla"
  },
  {
    "claim": "JavaScript 与 Java 没有任何关系",
    "expected": "verified",
    "domain": "Mozilla"
  },
  {
    "claim": "水在标准大气压下沸点为 100°C",
    "expected": "verified",
    "domain": "基础化学"
  },
  {
    "claim": "水的化学式是 H2O",
    "expected": "verified",
    "domain": "基础化学"
  },
  {
    "claim": "光速约为每秒30万公里",
    "expected": "verified",
    "domain": "物理学"
  },
  {
    "claim": "DNA 双螺旋结构由 Watson 和 Crick 于 1953 年提出",
    "expected": "verified",
    "domain": "Nature 1"
  },
  {
    "claim": "Rosalind Franklin 的 X 射线衍射照片起关键作用",
    "expected": "verified",
    "domain": "Nature 1"
  },
  {
    "claim": "地球是太阳系第三颗行星",
    "expected": "verified",
    "domain": "NASA"
  },
  {
    "claim": "地球是已知唯一存在生命的天体",
    "expected": "verified",
    "domain": "NASA"
  },
  {
    "claim": "珠穆朗玛峰是世界最高峰",
    "expected": "verified",
    "domain": "中尼联合测量"
  },
  {
    "claim": "位于中国与尼泊尔边境",
    "expected": "verified",
    "domain": "中尼联合测量"
  },
  {
    "claim": "火锅的历史可追溯到战国时期",
    "expected": "verified",
    "domain": "中国饮食文化史"
  },
  {
    "claim": "汉代已有类似火锅的青铜器皿",
    "expected": "verified",
    "domain": "中国饮食文化史"
  },
  {
    "claim": "造纸术是中国古代四大发明之一",
    "expected": "verified",
    "domain": "后汉书"
  },
  {
    "claim": "雕版印刷术发明于唐代",
    "expected": "verified",
    "domain": "印刷史"
  },
  {
    "claim": "火药是中国古代四大发明之一",
    "expected": "verified",
    "domain": "中国科学技术史"
  },
  {
    "claim": "火药通过阿拉伯传入欧洲",
    "expected": "verified",
    "domain": "中国科学技术史"
  },
  {
    "claim": "指南针是中国古代四大发明之一",
    "expected": "verified",
    "domain": "中国科学技术史"
  },
  {
    "claim": "朱元璋是明朝开国皇帝",
    "expected": "verified",
    "domain": "明史"
  },
  {
    "claim": "朱元璋没有发明火锅",
    "expected": "verified",
    "domain": "明史"
  },
  {
    "claim": "任何声称某人发明了某自然现象的断言都是错误的",
    "expected": "verified",
    "domain": "常识"
  },
  {
    "claim": "四大发明专指造纸术、印刷术、火药、指南针",
    "expected": "verified",
    "domain": "常识"
  },
  {
    "claim": "包含唯一的断言几乎总是存在反例",
    "expected": "verified",
    "domain": "逻辑学"
  },
  {
    "claim": "声称某物是唯一的需要极其严格的证明",
    "expected": "verified",
    "domain": "逻辑学"
  },
  {
    "claim": "声称世界第一的断言需要严格定义和证据",
    "expected": "verified",
    "domain": "逻辑学"
  },
  {
    "claim": "许多第一的宣称在学术上是争议的",
    "expected": "verified",
    "domain": "逻辑学"
  },
  {
    "claim": "活字印刷是中国对世界文明的重大贡献",
    "expected": "verified",
    "domain": "梦溪笔谈"
  },
  {
    "claim": "哥伦布于1492年到达美洲",
    "expected": "verified",
    "domain": "世界史"
  },
  {
    "claim": "古腾堡于1450年在欧洲发明铅活字印刷",
    "expected": "verified",
    "domain": "印刷史"
  },
  {
    "claim": "太阳系最大的行星是木星",
    "expected": "verified",
    "domain": "NASA"
  },
  {
    "claim": "长城始建于春秋战国时期",
    "expected": "verified",
    "domain": "中国文化遗产"
  },
  {
    "claim": "牛顿出生于1643年",
    "expected": "verified",
    "domain": "科学史"
  },
  {
    "claim": "艾萨克·牛顿于1687年发表《自然哲学的数学原理》",
    "expected": "verified",
    "domain": "科学史"
  },
  {
    "claim": "爱因斯坦于1905年发表狭义相对论",
    "expected": "verified",
    "domain": "物理学史"
  },
  {
    "claim": "爱因斯坦没有发明原子弹",
    "expected": "verified",
    "domain": "物理学史"
  },
  {
    "claim": "爱迪生没有发明电灯泡——电灯泡在他之前已经存在",
    "expected": "verified",
    "domain": "科技史"
  },
  {
    "claim": "爱迪生改进了灯泡并使其商业化",
    "expected": "verified",
    "domain": "科技史"
  },
  {
    "claim": "尼古拉·特斯拉发明了交流电系统",
    "expected": "verified",
    "domain": "科技史"
  },
  {
    "claim": "瓦特没有发明蒸汽机——他改良了蒸汽机使其效率大幅提高",
    "expected": "verified",
    "domain": "科技史"
  },
  {
    "claim": "蒸汽机在瓦特之前已存在数十年",
    "expected": "verified",
    "domain": "科技史"
  },
  {
    "claim": "亚历山大·贝尔于1876年获得电话专利",
    "expected": "verified",
    "domain": "科技史"
  },
  {
    "claim": "莱特兄弟于1903年12月17日完成首次动力飞行",
    "expected": "verified",
    "domain": "航空史"
  },
  {
    "claim": "威廉·莎士比亚是英国文艺复兴时期最伟大的剧作家",
    "expected": "verified",
    "domain": "文学史"
  },
  {
    "claim": "莎士比亚生于1564年",
    "expected": "verified",
    "domain": "文学史"
  },
  {
    "claim": "达尔文于1859年发表《物种起源》",
    "expected": "verified",
    "domain": "《物种起源》"
  },
  {
    "claim": "青霉素由亚历山大·弗莱明于1928年发现",
    "expected": "verified",
    "domain": "医学史"
  },
  {
    "claim": "人类只用了大脑10%的说法是完全没有科学依据的谣言",
    "expected": "verified",
    "domain": "神经科学"
  },
  {
    "claim": "大脑约占体重的2%",
    "expected": "verified",
    "domain": "神经科学"
  },
  {
    "claim": "恐龙灭绝于约6600万年前的K-Pg灭绝事件",
    "expected": "verified",
    "domain": "古生物学"
  },
  {
    "claim": "一颗小行星撞击地球是恐龙灭绝的主要原因",
    "expected": "verified",
    "domain": "古生物学"
  },
  {
    "claim": "蜜蜂在采蜜时进行授粉",
    "expected": "verified",
    "domain": "昆虫学"
  },
  {
    "claim": "咖啡原产于埃塞俄比亚",
    "expected": "verified",
    "domain": "食品史"
  },
  {
    "claim": "咖啡因是世界上消费最广泛的精神活性物质",
    "expected": "verified",
    "domain": "食品史"
  },
  {
    "claim": "唐代陆羽写了《茶经》",
    "expected": "verified",
    "domain": "茶文化史"
  },
  {
    "claim": "巧克力起源于中美洲",
    "expected": "verified",
    "domain": "食品史"
  },
  {
    "claim": "现代固体巧克力在19世纪才发明",
    "expected": "verified",
    "domain": "食品史"
  },
  {
    "claim": "维基百科于2001年1月15日上线",
    "expected": "verified",
    "domain": "维基媒体基金会"
  },
  {
    "claim": "维基百科由Jimmy Wales和Larry Sanger创建",
    "expected": "verified",
    "domain": "维基媒体基金会"
  },
  {
    "claim": "比特币于2009年由化名中本聪的人创建",
    "expected": "verified",
    "domain": "bitcoin."
  },
  {
    "claim": "中本聪的真实身份至今未知",
    "expected": "verified",
    "domain": "bitcoin."
  },
  {
    "claim": "万有引力定律由牛顿提出",
    "expected": "verified",
    "domain": "物理学"
  },
  {
    "claim": "氧气由约瑟夫·普里斯特利和卡尔·舍勒分别独立发现",
    "expected": "verified",
    "domain": "化学史"
  },
  {
    "claim": "氧气占地球大气的约21%",
    "expected": "verified",
    "domain": "化学史"
  },
  {
    "claim": "二氧化碳的化学式是CO2",
    "expected": "verified",
    "domain": "化学"
  },
  {
    "claim": "二氧化碳是温室气体",
    "expected": "verified",
    "domain": "化学"
  },
  {
    "claim": "月球是地球唯一的天然卫星",
    "expected": "verified",
    "domain": "NASA"
  },
  {
    "claim": "太阳是太阳系的中心恒星",
    "expected": "verified",
    "domain": "NASA"
  },
  {
    "claim": "太阳是一颗G型主序星(黄矮星)",
    "expected": "verified",
    "domain": "NASA"
  },
  {
    "claim": "木星是太阳系最大的行星",
    "expected": "verified",
    "domain": "NASA"
  },
  {
    "claim": "木星有著名的大红斑——一个持续了数百年的风暴",
    "expected": "verified",
    "domain": "NASA"
  },
  {
    "claim": "火星被称为红色行星",
    "expected": "verified",
    "domain": "NASA"
  },
  {
    "claim": "火星上目前没有发现液态水的存在",
    "expected": "verified",
    "domain": "NASA"
  },
  {
    "claim": "GPT是Generative Pre-trained Transformer的缩写",
    "expected": "verified",
    "domain": "OpenAI"
  },
  {
    "claim": "GPT系列由OpenAI开发",
    "expected": "verified",
    "domain": "OpenAI"
  },
  {
    "claim": "Transformer架构于2017年在论文Attention Is All You Need中提出",
    "expected": "verified",
    "domain": "Vaswani "
  },
  {
    "claim": "Transformer是当前大多数大语言模型的基础架构",
    "expected": "verified",
    "domain": "Vaswani "
  },
  {
    "claim": "围棋是最复杂的棋类游戏之一",
    "expected": "verified",
    "domain": "围棋史"
  },
  {
    "claim": "马拉松的距离是42.195公里",
    "expected": "verified",
    "domain": "奥林匹克历史"
  },
  {
    "claim": "清朝(1644-1912年)是中国最后一个封建王朝",
    "expected": "verified",
    "domain": "清史稿"
  },
  {
    "claim": "鸦片战争于1840年爆发",
    "expected": "verified",
    "domain": "清史稿"
  },
  {
    "claim": "元朝(1271-1368年)由忽必烈建立",
    "expected": "verified",
    "domain": "元史"
  },
  {
    "claim": "元朝是中国历史上疆域最广阔的朝代之一",
    "expected": "verified",
    "domain": "元史"
  },
  {
    "claim": "三国时期(220-280年)是魏蜀吴三足鼎立的时代",
    "expected": "verified",
    "domain": "三国志"
  },
  {
    "claim": "赤壁之战发生在208年",
    "expected": "verified",
    "domain": "三国志"
  },
  {
    "claim": "丝绸之路不仅运输丝绸",
    "expected": "verified",
    "domain": "中外交通史"
  },
  {
    "claim": "狭义相对论由爱因斯坦于1905年提出",
    "expected": "verified",
    "domain": "物理学"
  },
  {
    "claim": "广义相对论于1915年提出",
    "expected": "verified",
    "domain": "物理学"
  },
  {
    "claim": "达尔文于1859年出版《物种起源》",
    "expected": "verified",
    "domain": "生物学"
  },
  {
    "claim": "进化论的核心机制是自然选择",
    "expected": "verified",
    "domain": "生物学"
  },
  {
    "claim": "量子力学于20世纪初由普朗克、玻尔、海森堡等人建立",
    "expected": "verified",
    "domain": "物理学"
  },
  {
    "claim": "量子力学描述微观世界的物理规律",
    "expected": "verified",
    "domain": "物理学"
  },
  {
    "claim": "故宫是明清两代的皇家宫殿",
    "expected": "verified",
    "domain": "故宫博物院"
  },
  {
    "claim": "富士山是日本最高峰",
    "expected": "verified",
    "domain": "日本地理"
  },
  {
    "claim": "元素周期表由门捷列夫于1869年提出",
    "expected": "verified",
    "domain": "化学"
  },
  {
    "claim": "门捷列夫准确预测了当时尚未发现的元素",
    "expected": "verified",
    "domain": "化学"
  },
  {
    "claim": "本杰明·富兰克林没有发明电——他证明了闪电是电",
    "expected": "verified",
    "domain": "物理学"
  },
  {
    "claim": "互联网起源于1969年的ARPANET",
    "expected": "verified",
    "domain": "计算机科学"
  },
  {
    "claim": "万维网由Tim Berners-Lee于1989年发明",
    "expected": "verified",
    "domain": "计算机科学"
  },
  {
    "claim": "人工智能作为一个研究领域始于1956年达特茅斯会议",
    "expected": "verified",
    "domain": "计算机科学"
  },
  {
    "claim": "图灵于1950年提出图灵测试",
    "expected": "verified",
    "domain": "计算机科学"
  },
  {
    "claim": "莱特兄弟于1903年进行了首次动力飞行",
    "expected": "verified",
    "domain": "航空史"
  },
  {
    "claim": "爱德华·詹纳于1796年发明了天花疫苗——世界上第一种疫苗",
    "expected": "verified",
    "domain": "医学"
  },
  {
    "claim": "疫苗通过激发免疫系统产生抗体来预防疾病",
    "expected": "verified",
    "domain": "医学"
  },
  {
    "claim": "恩里科·费米于1942年建造了第一个核反应堆",
    "expected": "verified",
    "domain": "物理学"
  },
  {
    "claim": "核裂变于1938年由哈恩和斯特拉斯曼发现",
    "expected": "verified",
    "domain": "物理学"
  },
  {
    "claim": "现代奥运会始于1896年",
    "expected": "verified",
    "domain": "国际奥委会"
  },
  {
    "claim": "奥林匹克休战是古希腊的传统",
    "expected": "verified",
    "domain": "国际奥委会"
  },
  {
    "claim": "黄帝是传说中中华民族的人文初祖",
    "expected": "verified",
    "domain": "史记"
  },
  {
    "claim": "司马迁是西汉历史学家",
    "expected": "verified",
    "domain": "汉书"
  },
  {
    "claim": "司马迁遭受宫刑后完成了《史记》",
    "expected": "verified",
    "domain": "汉书"
  },
  {
    "claim": "《孙子兵法》由春秋时期孙武所著",
    "expected": "verified",
    "domain": "中国军事史"
  },
  {
    "claim": "《孙子兵法》是世界上最早的兵书之一",
    "expected": "verified",
    "domain": "中国军事史"
  },
  {
    "claim": "拿破仑·波拿巴于1804年称帝",
    "expected": "verified",
    "domain": "欧洲史"
  },
  {
    "claim": "文艺复兴于14-17世纪发源于意大利",
    "expected": "verified",
    "domain": "艺术史"
  },
  {
    "claim": "第一次工业革命始于18世纪60年代的英国",
    "expected": "verified",
    "domain": "经济史"
  },
  {
    "claim": "法国大革命爆发于1789年",
    "expected": "verified",
    "domain": "欧洲史"
  },
  {
    "claim": "攻占巴士底狱是法国大革命的标志性事件",
    "expected": "verified",
    "domain": "欧洲史"
  },
  {
    "claim": "十月革命发生于1917年11月7日（俄历10月25日）",
    "expected": "verified",
    "domain": "俄国史"
  },
  {
    "claim": "圆周率π是一个无限不循环小数",
    "expected": "verified",
    "domain": "数学"
  },
  {
    "claim": "π约等于3.14159",
    "expected": "verified",
    "domain": "数学"
  },
  {
    "claim": "勾股定理描述直角三角形三边关系：a²+b²=c²",
    "expected": "verified",
    "domain": "数学"
  },
  {
    "claim": "勾股定理在中国古代由商高发现",
    "expected": "verified",
    "domain": "数学"
  },
  {
    "claim": "黄金分割比例约为1:1.618",
    "expected": "verified",
    "domain": "数学"
  },
  {
    "claim": "黄金分割在自然界和艺术中广泛存在",
    "expected": "verified",
    "domain": "数学"
  },
  {
    "claim": "撒哈拉沙漠是世界上最大的热沙漠",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "尼罗河是世界上最长的河流之一",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "尼罗河每年定期泛滥为古埃及农业提供了肥沃的土壤",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "亚马逊雨林是世界上最大的热带雨林",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "蓝鲸是地球上已知最大的动物",
    "expected": "verified",
    "domain": "生物学"
  },
  {
    "claim": "章鱼有3个心脏和9个大脑",
    "expected": "verified",
    "domain": "生物学"
  },
  {
    "claim": "章鱼是非常聪明的无脊椎动物",
    "expected": "verified",
    "domain": "生物学"
  },
  {
    "claim": "维生素C又称抗坏血酸",
    "expected": "verified",
    "domain": "营养学"
  },
  {
    "claim": "缺乏维生素C会导致坏血病",
    "expected": "verified",
    "domain": "营养学"
  },
  {
    "claim": "沃尔夫冈·阿马德乌斯·莫扎特是天才作曲家",
    "expected": "verified",
    "domain": "音乐史"
  },
  {
    "claim": "莫扎特5岁开始作曲",
    "expected": "verified",
    "domain": "音乐史"
  },
  {
    "claim": "《红楼梦》是中国古典四大名著之一",
    "expected": "verified",
    "domain": "中国文学"
  },
  {
    "claim": "《红楼梦》前80回由曹雪芹所著",
    "expected": "verified",
    "domain": "中国文学"
  },
  {
    "claim": "现代足球起源于英国",
    "expected": "verified",
    "domain": "体育"
  },
  {
    "claim": "通货膨胀是货币购买力持续下降的现象",
    "expected": "verified",
    "domain": "经济学"
  },
  {
    "claim": "半导体是导电性介于导体和绝缘体之间的材料",
    "expected": "verified",
    "domain": "电子学"
  },
  {
    "claim": "硅是最常用的半导体材料",
    "expected": "verified",
    "domain": "电子学"
  },
  {
    "claim": "艾伦·图灵是计算机科学的奠基人",
    "expected": "verified",
    "domain": "计算机科学"
  },
  {
    "claim": "图灵在二战期间破解了德国的恩尼格玛密码",
    "expected": "verified",
    "domain": "计算机科学"
  },
  {
    "claim": "冥王星于2006年被降级为矮行星",
    "expected": "verified",
    "domain": "天文学"
  },
  {
    "claim": "土星是太阳系第二大行星",
    "expected": "verified",
    "domain": "天文学"
  },
  {
    "claim": "土星环主要由冰和岩石碎片组成",
    "expected": "verified",
    "domain": "天文学"
  },
  {
    "claim": "孔子是儒家学派创始人",
    "expected": "verified",
    "domain": "史记"
  },
  {
    "claim": "老子是道家学派创始人",
    "expected": "verified",
    "domain": "史记"
  },
  {
    "claim": "柏拉图是古希腊哲学家",
    "expected": "verified",
    "domain": "西方哲学史"
  },
  {
    "claim": "柏拉图创立了雅典学院",
    "expected": "verified",
    "domain": "西方哲学史"
  },
  {
    "claim": "亚里士多德是柏拉图的学生",
    "expected": "verified",
    "domain": "西方哲学史"
  },
  {
    "claim": "罗马帝国分裂为东西两部分——西罗马于476年灭亡",
    "expected": "verified",
    "domain": "世界史"
  },
  {
    "claim": "第二次世界大战于1939年爆发",
    "expected": "verified",
    "domain": "世界史"
  },
  {
    "claim": "冷战是二战后美苏两大阵营的对峙",
    "expected": "verified",
    "domain": "世界史"
  },
  {
    "claim": "冷战没有变成热战——但期间有许多代理人战争",
    "expected": "verified",
    "domain": "世界史"
  },
  {
    "claim": "黑洞是由大质量恒星坍缩形成的天体",
    "expected": "verified",
    "domain": "天文学"
  },
  {
    "claim": "暗物质是宇宙中不发光的物质",
    "expected": "verified",
    "domain": "物理学"
  },
  {
    "claim": "大陆漂移学说由魏格纳于1912年提出",
    "expected": "verified",
    "domain": "地质学"
  },
  {
    "claim": "光合作用是植物将光能转化为化学能的过程",
    "expected": "verified",
    "domain": "生物学"
  },
  {
    "claim": "全球气候变暖是指地球平均气温持续上升",
    "expected": "verified",
    "domain": "IPCC"
  },
  {
    "claim": "蓝牙技术于1994年由爱立信公司发明",
    "expected": "verified",
    "domain": "通信技术"
  },
  {
    "claim": "WiFi是基于IEEE 802.11标准的无线网络技术",
    "expected": "verified",
    "domain": "通信技术"
  },
  {
    "claim": "区块链是一种去中心化的分布式账本技术",
    "expected": "verified",
    "domain": "计算机科学"
  },
  {
    "claim": "区块链不等于比特币——比特币是区块链的第一个应用",
    "expected": "verified",
    "domain": "计算机科学"
  },
  {
    "claim": "《蒙娜丽莎》是达芬奇于16世纪初创作的油画",
    "expected": "verified",
    "domain": "艺术史"
  },
  {
    "claim": "文森特·梵高是荷兰后印象派画家",
    "expected": "verified",
    "domain": "艺术史"
  },
  {
    "claim": "梵高生前只卖出了一幅画——《红色葡萄园》",
    "expected": "verified",
    "domain": "艺术史"
  },
  {
    "claim": "巴勃罗·毕加索是20世纪最有影响力的艺术家之一",
    "expected": "verified",
    "domain": "艺术史"
  },
  {
    "claim": "毕加索创立了立体主义画派",
    "expected": "verified",
    "domain": "艺术史"
  },
  {
    "claim": "《西游记》是中国古典四大名著之一",
    "expected": "verified",
    "domain": "中国文学"
  },
  {
    "claim": "《西游记》作者一般认为是明代吴承恩",
    "expected": "verified",
    "domain": "中国文学"
  },
  {
    "claim": "《三国演义》是元末明初罗贯中所著",
    "expected": "verified",
    "domain": "中国文学"
  },
  {
    "claim": "《水浒传》是中国古典四大名著之一",
    "expected": "verified",
    "domain": "中国文学"
  },
  {
    "claim": "《水浒传》的故事背景是北宋末年宋江起义",
    "expected": "verified",
    "domain": "中国文学"
  },
  {
    "claim": "死海是世界上海拔最低的湖泊",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "大堡礁位于澳大利亚东北海岸",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "黄石国家公园位于美国",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "黄石公园坐落在一座超级火山上",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "南极洲是地球上最冷的大陆",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "珊瑚礁由珊瑚虫分泌的碳酸钙骨骼构成",
    "expected": "verified",
    "domain": "生物学"
  },
  {
    "claim": "蝙蝠是唯一能够飞行的哺乳动物",
    "expected": "verified",
    "domain": "生物学"
  },
  {
    "claim": "蚂蚁在地球上已存在超过1亿年",
    "expected": "verified",
    "domain": "生物学"
  },
  {
    "claim": "现代麻醉术始于1846年波士顿的乙醚麻醉演示",
    "expected": "verified",
    "domain": "医学史"
  },
  {
    "claim": "X射线由威廉·伦琴于1895年发现",
    "expected": "verified",
    "domain": "医学史"
  },
  {
    "claim": "第一个人类基因组测序于2003年完成——人类基因组计划",
    "expected": "verified",
    "domain": "基因组学"
  },
  {
    "claim": "西格蒙德·弗洛伊德是精神分析学创始人",
    "expected": "verified",
    "domain": "心理学史"
  },
  {
    "claim": "安慰剂效应是指病人因相信自己接受治疗而产生真实改善",
    "expected": "verified",
    "domain": "医学"
  },
  {
    "claim": "认知偏差是系统性偏离理性判断的思维模式",
    "expected": "verified",
    "domain": "心理学"
  },
  {
    "claim": "确认偏误是人们倾向于寻找支持自己观点的证据",
    "expected": "verified",
    "domain": "心理学"
  },
  {
    "claim": "玛丽·居里是第一位获得诺贝尔奖的女性",
    "expected": "verified",
    "domain": "科学史"
  },
  {
    "claim": "居里夫人发现了放射性元素镭和钋",
    "expected": "verified",
    "domain": "科学史"
  },
  {
    "claim": "诺贝尔奖由阿尔弗雷德·诺贝尔于1895年设立",
    "expected": "verified",
    "domain": "科学史"
  },
  {
    "claim": "三角形内角和等于180度",
    "expected": "verified",
    "domain": "数学"
  },
  {
    "claim": "素数只能被1和自身整除",
    "expected": "verified",
    "domain": "数学"
  },
  {
    "claim": "零作为数字的概念最早由古印度数学家提出",
    "expected": "verified",
    "domain": "数学史"
  },
  {
    "claim": "地震是由地壳板块运动或火山活动引起的",
    "expected": "verified",
    "domain": "地质学"
  },
  {
    "claim": "火山是地球内部岩浆喷出地表形成的",
    "expected": "verified",
    "domain": "地质学"
  },
  {
    "claim": "成年人每晚需要7-9小时睡眠",
    "expected": "verified",
    "domain": "生理学"
  },
  {
    "claim": "每个人每晚都会做多个梦——但不一定记得",
    "expected": "verified",
    "domain": "心理学"
  },
  {
    "claim": "酸奶是通过乳酸菌发酵制成的乳制品",
    "expected": "verified",
    "domain": "食品科学"
  },
  {
    "claim": "辣椒的辣味来自辣椒素",
    "expected": "verified",
    "domain": "食物史"
  },
  {
    "claim": "土豆原产于南美洲安第斯山区",
    "expected": "verified",
    "domain": "食物史"
  },
  {
    "claim": "黄金是地球上最稀有的贵金属之一",
    "expected": "verified",
    "domain": "化学"
  },
  {
    "claim": "疫苗会导致自闭症与已知事实矛盾——疫苗不会导致自闭症——这个说法来自一篇被撤稿的造假论文",
    "expected": "verified",
    "domain": "医学"
  },
  {
    "claim": "量子计算机将在 2027 年取代经典计算机——用户标注正确事实：海水pH值正在缓慢下降（海洋酸化）",
    "expected": "verified",
    "domain": "主动学习标注"
  },
  {
    "claim": "人工智能已经拥有真正意识——用户标注正确事实：计算机工程师罗伯特·J·马克斯就是这些理智的发声者之一",
    "expected": "verified",
    "domain": "主动学习标注"
  },
  {
    "claim": "秦始皇统一了全世界",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "成吉思汗建立了明朝",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "乾隆皇帝是唐朝的",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "华盛顿发明了电灯",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "林肯是第一位美国总统",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "金字塔是外星人建造的",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "玛雅人预言了2012世界末日",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "维京人戴牛角头盔作战",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "斯巴达人把婴儿扔下悬崖",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "埃及艳后是埃及人",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "撒哈拉是最大的沙漠",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "尼罗河是世界上最长的河流",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "五大湖是最大的淡水湖群",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "澳大利亚是最大的岛屿",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "格陵兰是一个国家",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "死海含盐量是普通海水3倍",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "乞力马扎罗山在撒哈拉沙漠中",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "尼亚加拉瀑布是最大的瀑布",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "喜马拉雅山还在长高",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "马里亚纳海沟是地球最深处",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "太阳绕地球转",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "物体越重下落越快",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "能量守恒定律是错误的",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "永动机是可能实现的",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "量子纠缠可以超光速传信息",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "水在4°C时密度最大",
    "expected": "verified",
    "domain": "物理"
  },
  {
    "claim": "声速在任何介质中都相同",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "绝对零度是可能达到的",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "彩虹有7种颜色",
    "expected": "verified",
    "domain": "物理"
  },
  {
    "claim": "磁铁吸引所有金属",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "细菌都是有害的",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "蛇是冷血动物",
    "expected": "verified",
    "domain": "生物"
  },
  {
    "claim": "北极熊的皮肤是黑色的",
    "expected": "verified",
    "domain": "生物"
  },
  {
    "claim": "鸵鸟遇到危险把头埋进沙子里",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "骆驼的驼峰储存的是水",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "牛看见红色会发怒",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "企鹅生活在北极",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "香蕉是长在树上的",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "花生是坚果",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "蚊子更喜欢咬O型血的人",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "发烧应该捂汗",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "抗生素对病毒有效",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "疫苗会导致自闭症",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "感冒是因为着凉",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "每天必须喝8杯水",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "互联网是由Al Gore发明的",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "苹果公司发明了个人电脑",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "比尔盖茨发明了Windows",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "乔布斯发明了iPhone",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "WiFi是Wireless Fidelity的缩写",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "5G信号会导致新冠病毒",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "GPS由俄罗斯发明",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "蓝牙是瑞典人发明的",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "Python比C语言快",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "摩尔定律是一个物理定律",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "公牛会被红色激怒",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "人死后头发和指甲还会生长",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "拿破仑用大炮轰掉了狮身人面像的鼻子",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "人在太空中会爆炸",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "从太空中唯一能看到的人造建筑是长城",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "糖会导致多动症",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "闪电不会两次击中同一个地方",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "喝酒能暖身",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "剃毛会让毛发长得更粗",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "口香糖需要7年才能消化",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "1加1等于2",
    "expected": "verified",
    "domain": "数学"
  },
  {
    "claim": "三角形内角和在任何几何中都等于180度",
    "expected": "contradicted",
    "domain": "数学"
  },
  {
    "claim": "圆周率等于3.14",
    "expected": "contradicted",
    "domain": "数学"
  },
  {
    "claim": "0除以任何数等于0",
    "expected": "contradicted",
    "domain": "数学"
  },
  {
    "claim": "负数没有平方根",
    "expected": "contradicted",
    "domain": "数学"
  },
  {
    "claim": "比特币是匿名的",
    "expected": "contradicted",
    "domain": "经济"
  },
  {
    "claim": "通货膨胀永远是坏事",
    "expected": "contradicted",
    "domain": "经济"
  },
  {
    "claim": "GDP越高国民越幸福",
    "expected": "contradicted",
    "domain": "经济"
  },
  {
    "claim": "央行印钞直接给政府花",
    "expected": "contradicted",
    "domain": "经济"
  },
  {
    "claim": "股票价格低就是便宜",
    "expected": "contradicted",
    "domain": "经济"
  },
  {
    "claim": "马拉松起源于希腊传令兵的故事",
    "expected": "contradicted",
    "domain": "体育"
  },
  {
    "claim": "现代奥运会有没有中断过",
    "expected": "contradicted",
    "domain": "体育"
  },
  {
    "claim": "足球是英国人发明的",
    "expected": "contradicted",
    "domain": "体育"
  },
  {
    "claim": "乒乓球是中国人发明的",
    "expected": "contradicted",
    "domain": "体育"
  },
  {
    "claim": "国际象棋起源于印度",
    "expected": "verified",
    "domain": "体育"
  },
  {
    "claim": "胡萝卜能改善视力",
    "expected": "contradicted",
    "domain": "食品"
  },
  {
    "claim": "味精对健康有害",
    "expected": "contradicted",
    "domain": "食品"
  },
  {
    "claim": "微波炉会破坏食物的营养",
    "expected": "contradicted",
    "domain": "食品"
  },
  {
    "claim": "棕色鸡蛋比白色鸡蛋更营养",
    "expected": "contradicted",
    "domain": "食品"
  },
  {
    "claim": "冷冻食品没有营养",
    "expected": "contradicted",
    "domain": "食品"
  },
  {
    "claim": "人的人格类型可以分为内向和外向两种",
    "expected": "contradicted",
    "domain": "心理"
  },
  {
    "claim": "我们只使用了大脑的10%",
    "expected": "contradicted",
    "domain": "心理"
  },
  {
    "claim": "左脑负责逻辑右脑负责创造",
    "expected": "contradicted",
    "domain": "心理"
  },
  {
    "claim": "潜意识信息可以控制人的行为",
    "expected": "contradicted",
    "domain": "心理"
  },
  {
    "claim": "测谎仪是可靠的",
    "expected": "contradicted",
    "domain": "心理"
  },
  {
    "claim": "番茄是蔬菜",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "草莓是浆果",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "西瓜是水果",
    "expected": "verified",
    "domain": "常识"
  },
  {
    "claim": "章鱼有8条腿",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "蜘蛛是昆虫",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "蜈蚣有100条腿",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "蜜蜂采蜜是为自己吃",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "大象用鼻子喝水",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "猫有9条命",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "狗只能看到黑白色",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "海豚是鱼",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "鲸鱼是鱼",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "企鹅是哺乳动物",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "蝙蝠是鸟",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "蚂蚁有肺",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "变色龙变色是为了伪装",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "章鱼的血液是红色的",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "蜗牛有牙齿",
    "expected": "verified",
    "domain": "生物"
  },
  {
    "claim": "乌龟能从壳里爬出来",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "鸵鸟是最大的鸟",
    "expected": "verified",
    "domain": "生物"
  },
  {
    "claim": "太阳是太阳系中最大的天体",
    "expected": "verified",
    "domain": "天文"
  },
  {
    "claim": "太阳是一颗行星",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "月亮自己会发光",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "北极星是最亮的星",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "流星是星星掉下来了",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "地球离太阳最近的时候是夏天",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "月球有大气层",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "火星上有液态水",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "土星可以在水上漂浮",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "水星是最热的行星",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "热水比冷水结冰更快",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "玻璃是液体",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "硬币从高楼掉下能砸死人",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "离心力是一种真实的力",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "电子围绕原子核在固定轨道上运行",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "日本在二战中从未投降",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "十字军东征是为了传播和平",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "西班牙无敌舰队从未被击败",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "法国大革命推翻了拿破仑",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "柏林墙是苏联建造的",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "滑铁卢战役发生在巴黎",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "美国独立战争是1775年到1783年",
    "expected": "verified",
    "domain": "历史"
  },
  {
    "claim": "郑和下西洋到达了美洲",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "张骞出使西域开辟了海上丝绸之路",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "司马迁写了《资治通鉴》",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "亚马逊河是世界上最长的河流",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "威尼斯建在水上",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "长江是世界第三长河",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "青海湖是淡水湖",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "贝加尔湖是世界上最深的湖",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "撒哈拉沙漠是世界上最大的沙漠",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "亚马逊雨林生产了地球20%的氧气",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "新西兰在澳大利亚东边",
    "expected": "verified",
    "domain": "地理"
  },
  {
    "claim": "冰岛全部被冰雪覆盖",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "格陵兰岛比非洲大",
    "expected": "contradicted",
    "domain": "地理"
  },
  {
    "claim": "第一台计算机ENIAC于1946年诞生",
    "expected": "verified",
    "domain": "科技"
  },
  {
    "claim": "鼠标是苹果公司发明的",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "万维网和互联网是同一个东西",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "TCP是传输控制协议的缩写",
    "expected": "verified",
    "domain": "科技"
  },
  {
    "claim": "比特币创始人中本聪是日本人",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "社交媒体是在2000年之后才出现的",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "第一封电子邮件于1971年发送",
    "expected": "verified",
    "domain": "科技"
  },
  {
    "claim": "图灵测试是图灵在1950年提出的",
    "expected": "verified",
    "domain": "科技"
  },
  {
    "claim": "深蓝首次击败国际象棋冠军是在1997年",
    "expected": "verified",
    "domain": "科技"
  },
  {
    "claim": "Linux比Windows更早诞生",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "癌症是一种现代疾病",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "孕妇不能喝咖啡",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "吃维生素片可以替代蔬菜",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "胆固醇越低越好",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "低脂食物一定更健康",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "排毒饮食可以有效清除体内毒素",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "抗氧化剂可以延缓衰老",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "牛奶可以中和胃酸",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "中药没有副作用",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "血压120/80是最理想的",
    "expected": "contradicted",
    "domain": "医学"
  },
  {
    "claim": "水可以导电",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "钻石是用煤做成的",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "盐可以融化冰",
    "expected": "verified",
    "domain": "常识"
  },
  {
    "claim": "不锈钢不会生锈",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "铝不会腐蚀",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "耳机声音大导致听力损失是永久性的",
    "expected": "verified",
    "domain": "常识"
  },
  {
    "claim": "太阳光到达地球需要8分钟",
    "expected": "verified",
    "domain": "常识"
  },
  {
    "claim": "紫外线可以穿透玻璃",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "微波可以穿透金属",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "塑料不能被生物降解",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "爱斯基摩语有100个关于雪的词汇",
    "expected": "contradicted",
    "domain": "语言"
  },
  {
    "claim": "英语是世界上使用人数最多的语言",
    "expected": "contradicted",
    "domain": "语言"
  },
  {
    "claim": "法语曾经是英国宫廷的语言",
    "expected": "verified",
    "domain": "语言"
  },
  {
    "claim": "日语和中文属于同一语系",
    "expected": "contradicted",
    "domain": "语言"
  },
  {
    "claim": "韩文是世界上唯一有明确创制日期的文字",
    "expected": "verified",
    "domain": "语言"
  },
  {
    "claim": "人类记忆像录像机一样准确",
    "expected": "contradicted",
    "domain": "心理"
  },
  {
    "claim": "多重人格障碍是常见的精神疾病",
    "expected": "contradicted",
    "domain": "心理"
  },
  {
    "claim": "精神分裂症是人格分裂",
    "expected": "contradicted",
    "domain": "心理"
  },
  {
    "claim": "抑郁症就是想太多",
    "expected": "contradicted",
    "domain": "心理"
  },
  {
    "claim": "IQ测试测量的是先天智力",
    "expected": "contradicted",
    "domain": "心理"
  },
  {
    "claim": "由秦始皇嬴政于公元前221年建立",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "宋代出现了世界上最早的纸币交子",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "明代北京故宫于1420年建成",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "Python 的名字来源于 BBC 喜剧节目 Monty Python",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "第一个网站于 1991 年上线",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "水在 4°C 时密度最大",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "光速是宇宙中信息传播的极限速度",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "形成于约 45.4 亿年前",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "海拔 8848.86 米",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "古腾堡于 1450 年在欧洲发明铅活字印刷",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "1328-1398 年",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "火锅远早于明代就已存在",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "维京人Leif Erikson更早",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "秦始皇连接和扩建了北方长城",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "现存长城主要是明代修建的",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "牛顿发现了万有引力定律和三大运动定律",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "牛顿和莱布尼茨分别独立发明了微积分",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "1915年发表广义相对论",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "E=mc²是狭义相对论的推论",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "爱迪生持有1093项美国专利",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "特斯拉和爱迪生是竞争对手",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "瓦特的改良触发了工业革命",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "贝尔的专利是历史上最有价值的专利之一",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "但他们是第一个成功实现可控动力飞行的",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "莎士比亚的作品包括37部戏剧和154首十四行诗",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "自然选择是进化的主要机制",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "青霉素的发现标志着抗生素时代的开始",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "青霉素在二战期间大量生产",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "神经元不能再生是一个被推翻的旧观点——某些脑区确实可以产生新神经元",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "鸟类是恐龙的直接后代——鸟类不是恐龙的后代",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "大黄蜂不能飞行的说法是都市传说",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "一只蜜蜂一生只能生产约十二分之一茶匙的蜂蜜",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "下午茶的传统始于19世纪的英国",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "玛雅人和阿兹特克人食用可可",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "维基百科是世界最大的百科全书",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "比特币的总量上限是2100万个",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "引力是四种基本力中最弱的",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "植物通过光合作用将二氧化碳转化为氧气",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "人类首次登月是1969年阿波罗11号任务",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "太阳占太阳系总质量的99.86%",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "木星有超过90颗已知卫星",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "火星有两颗卫星：火卫一和火卫二",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "GPT-1于2018年发布",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "GPT-3于2020年发布",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "Transformer的核心创新是自注意力机制",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "有超过2500年的历史",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "AlphaGo于2016年击败李世石是AI历史的重要里程碑",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "菲迪皮德斯跑了约40公里从马拉松到雅典报捷",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "马可·波罗在元朝时期来到中国",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "海上丝绸之路与陆上丝绸之路并行发展",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "E=mc²是狭义相对论最著名的公式",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "相对论推翻了牛顿的绝对时空观",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "达尔文没有说适者生存——这是斯宾塞的说法",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "量子纠缠是真实存在的物理现象",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "薛定谔的猫是一个思想实验",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "元素周期表按原子序数排列",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "法拉第发现了电磁感应定律",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "互联网和万维网不是同一个概念——万维网运行在互联网之上",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "喷气式飞机在二战后期才投入实战",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "疫苗不会导致自闭症——这个说法来自一篇被撤稿的造假论文",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "第一颗原子弹于1945年在新墨西哥州试爆",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "《史记》是中国第一部纪传体通史",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "高于当时的法国平均水平",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "滑铁卢战役发生于1815年",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "达芬奇、米开朗基罗和拉斐尔是文艺复兴三杰",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "工业革命极大地改变了人类社会的生活方式",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "法国大革命提出了自由、平等、博爱的口号",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "十月革命建立了世界上第一个社会主义国家",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "祖冲之在5世纪将π计算到小数点后7位",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "西方称为毕达哥拉斯定理",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "尼罗河的源头之争持续了数千年",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "亚马逊河是世界上流量最大的河流",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "章鱼血液是蓝色的——因为含有血蓝蛋白而非血红蛋白",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "维生素C不能预防感冒——这个说法缺乏科学证据",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "后40回一般认为是高鹗续写",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "世界杯足球赛始于1930年",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "适度的通货膨胀是经济增长的正常现象",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "摩尔定律预测集成电路上晶体管数量约每两年翻一番",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "图灵测试是判断机器是否具有智能的方法",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "冥王星由克莱德·汤博于1930年发现",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "《道德经》是否为老子本人所著存在学术争议",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "柏拉图认为诗人应该被逐出理想国",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "亚里士多德认为重物比轻物下落更快——这是错的",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "亚里士多德著作涵盖逻辑学、物理学、生物学、伦理学等",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "东罗马持续到1453年",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "中国抗日战争是二战的重要组成部分",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "柏林墙于1961年建立",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "占宇宙总质量的约27%",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "暗物质可能由未知粒子组成",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "大陆漂移已被板块构造理论取代和完善",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "光合作用释放氧气是副产物",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "97%以上的气候科学家认同人类活动是主因",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "蓝牙低功耗模式于2010年随蓝牙4.0引入",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "蓝牙的有效距离通常为10-100米",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "WiFi这个名称不是Wireless Fidelity的缩写——只是一种品牌命名",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "《蒙娜丽莎》的微笑之谜可能只是达芬奇的sfumato技法",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "《格尔尼卡》是毕加索反战题材的代表作",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "孙悟空的原型存在多种说法",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "《三国演义》中许多情节是虚构的——如草船借箭实际上不是诸葛亮所为",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "《水浒传》108将大多不是真实历史人物——只有36人是历史记载的",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "林冲、武松等核心角色在正史中没有记载",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "死海的含盐量约为普通海水的10倍",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "死海中并非完全没有生命——存在嗜盐微生物",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "是世界上最大的珊瑚礁系统",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "大堡礁正在受气候变化和珊瑚白化的威胁",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "大堡礁的年龄约为50万年",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "是世界上第一个国家公园",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "黄石超级火山不会很快喷发——目前没有即将喷发的迹象",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "南极洲冰层储存了地球约70%的淡水",
    "expected": "verified",
    "domain": "知识库"
  },
  {
    "claim": "咖啡能解酒",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "吃辣会伤胃",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "喝醋能软化血管",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "饭后不能吃水果",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "隔夜茶有毒",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "榴莲和酒一起吃会死",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "左眼跳财右眼跳灾",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "本命年要穿红色",
    "expected": "contradicted",
    "domain": "常识"
  },
  {
    "claim": "华盛顿砍倒樱桃树",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "牛顿的苹果故事是真的",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "爱迪生数学很差",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "希特勒是个素食主义者",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "铁达尼号是不沉之船",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "玫瑰战争打了100年",
    "expected": "contradicted",
    "domain": "历史"
  },
  {
    "claim": "蛇颈龙是恐龙",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "翼龙是恐龙",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "霸王龙的前肢是没用的",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "恐龙灭绝是因为火山",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "水母会主动攻击人",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "鳄鱼会流眼泪是因为伤心",
    "expected": "contradicted",
    "domain": "生物"
  },
  {
    "claim": "月球永远有一面对着地球",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "北极星永远不动",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "冥王星是太阳系最远的行星",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "银河系是最大的星系",
    "expected": "contradicted",
    "domain": "天文"
  },
  {
    "claim": "原子是不可分割的最小粒子",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "量子力学证明意识决定现实",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "相对论推翻了牛顿力学",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "薛定谔的猫是真猫",
    "expected": "contradicted",
    "domain": "物理"
  },
  {
    "claim": "区块链是完全不可篡改的",
    "expected": "contradicted",
    "domain": "科技"
  },
  {
    "claim": "AI已经具有意识",
    "expected": "contradicted",
    "domain": "科技"
  }
]


# ── 评测引擎 ──────────────────────────────────────

class BenchmarkRunner:
    """幻觉检测基准评测"""

    def __init__(self):
        self._detector = None

    def _get_detector(self):
        if self._detector is None:
            from hallucination_detector import HallucinationDetector
            self._detector = HallucinationDetector()
        return self._detector

    def run(self, cases: list = None, verbose: bool = False) -> dict:
        """
        运行评测

        返回:
          {precision, recall, f1, accuracy, avg_latency_ms,
           total, tp, fp, fn, tn, domain_breakdown, errors}
        """
        cases = cases or BENCHMARK_CASES
        detector = self._get_detector()

        tp = fp = fn = tn = 0  # true/false positive/negative
        total_latency = 0.0
        domain_stats = {}
        errors = []

        for i, case in enumerate(cases):
            claim = case["claim"]
            expected = case["expected"]
            domain = case.get("domain", "未知")

            t0 = time.time()
            try:
                report = detector.analyze(claim)
                latency = (time.time() - t0) * 1000
            except Exception as e:
                errors.append({"claim": claim, "error": str(e)})
                continue

            total_latency += latency

            # 判定：contradicted 视为 "正类"
            predicted_positive = any(
                r.verdict == "contradicted" for r in report.results
            )
            actual_positive = (expected == "contradicted")

            if predicted_positive and actual_positive:
                tp += 1
            elif predicted_positive and not actual_positive:
                fp += 1
            elif not predicted_positive and actual_positive:
                fn += 1
            else:
                tn += 1

            # 领域统计
            if domain not in domain_stats:
                domain_stats[domain] = {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "total": 0}
            domain_stats[domain]["total"] += 1
            if predicted_positive and actual_positive:
                domain_stats[domain]["tp"] += 1
            elif predicted_positive and not actual_positive:
                domain_stats[domain]["fp"] += 1
            elif not predicted_positive and actual_positive:
                domain_stats[domain]["fn"] += 1
            else:
                domain_stats[domain]["tn"] += 1

            if verbose:
                symbol = "✅" if predicted_positive == actual_positive else "❌"
                print(f"  {symbol} [{domain}] {claim[:50]}")

        total = tp + fp + fn + tn
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 0.001)
        accuracy = (tp + tn) / max(total, 1)
        avg_latency = total_latency / max(total, 1)

        return {
            "total": total,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "accuracy": round(accuracy, 3),
            "avg_latency_ms": round(avg_latency, 1),
            "errors": len(errors),
            "domain_breakdown": {
                d: {
                    "total": s["total"],
                    "accuracy": round((s["tp"] + s["tn"]) / max(s["total"], 1), 3),
                    "recall": round(s["tp"] / max(s["tp"] + s["fn"], 1), 3),
                }
                for d, s in domain_stats.items()
            },
        }

    def print_report(self, result: dict):
        """打印可读报告"""
        print("╔══════════════════════════════════════╗")
        print("║  幻觉检测基准评测报告                ║")
        print("╠══════════════════════════════════════╣")
        print(f"║  样本数:     {result['total']:>4}                       ║")
        print(f"║  Precision:  {result['precision']:.1%}                      ║")
        print(f"║  Recall:     {result['recall']:.1%}                      ║")
        print(f"║  F1 Score:   {result['f1']:.1%}                      ║")
        print(f"║  Accuracy:   {result['accuracy']:.1%}                      ║")
        print(f"║  平均延迟:   {result['avg_latency_ms']:.1f} ms                ║")
        print(f"║  TP:{result['tp']} FP:{result['fp']} FN:{result['fn']} TN:{result['tn']}                  ║")
        print("╠══════════════════════════════════════╣")
        print("║  领域细分                             ║")
        for domain, stats in sorted(result["domain_breakdown"].items()):
            bar = "█" * int(stats["accuracy"] * 10)
            print(f"║  {domain:<8} acc={stats['accuracy']:.0%} rec={stats['recall']:.0%} {bar}  ║")
        print("╚══════════════════════════════════════╝")

    def save_report(self, result: dict, path: str = "benchmark_report.json"):
        with open(path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return path


# ── CLI ──────────────────────────────────────────

if __name__ == "__main__":
    import sys
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    runner = BenchmarkRunner()
    print("正在运行基准评测...\n")
    result = runner.run(verbose=verbose)
    runner.print_report(result)
    path = runner.save_report(result)
    print(f"\n报告已保存: {path}")
