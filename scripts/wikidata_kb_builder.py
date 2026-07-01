#!/usr/bin/env python3
"""Wikidata 批量 KB 扩充 — 73,712 QID → 知识库"""
import json, time, urllib.request, urllib.parse
from pathlib import Path

WORKDIR = Path("/data/data/com.termux/files/home/workspace/hallucination_detector")
HEADERS = {"User-Agent": "AnchorKB/2.0 (batch builder; research)", "Accept-Encoding": "gzip"}
BATCH = 50
DELAY = 1.2

def api(params):
    """调用 Wikidata API"""
    params['format'] = 'json'
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 5 * (attempt + 1)
                print(f"  限流，等待{wait}秒...")
                time.sleep(wait)
            else:
                return None
        except Exception as e:
            if attempt < 4:
                time.sleep(3)
    return None

def load_all_qids() -> list[str]:
    """从所有 JSON 文件提取 QID"""
    qids = set()
    for fname in ['people_batch.json', 'people_batch2.json', 'wiki_entities.json']:
        fp = WORKDIR / fname
        if not fp.exists(): continue
        with open(fp) as f:
            data = json.load(f)
        for key, val in data.items():
            if isinstance(val, dict) and 'results' in val:
                for b in val['results'].get('bindings', []):
                    uri = b.get('item', {}).get('value', '')
                    if uri and 'Q' in uri:
                        qids.add(uri.split('/')[-1])
    return sorted(qids)

def resolve_labels(qid_set: set[str]) -> dict[str, str]:
    """批量解析 QID 到标签"""
    label_map = {}
    qid_list = sorted(qid_set)
    for i in range(0, len(qid_list), BATCH):
        batch = qid_list[i:i+BATCH]
        ids = '|'.join(batch)
        data = api({"action": "wbgetentities", "ids": ids, "props": "labels", "languages": "en"})
        if data:
            for qid, entity in data.get('entities', {}).items():
                if 'missing' not in entity:
                    label = entity.get('labels', {}).get('en', {}).get('value', '')
                    if label:
                        label_map[qid] = label
        if (i + 1) % 500 == 0:
            print(f"  标签解析: {i+1}/{len(qid_list)}")
        time.sleep(DELAY)
    return label_map

def extract_labels(kb: dict) -> set[str]:
    """从 KB 中提取所有需要解析的属性值 QID"""
    ref_qids = set()
    for entry in kb.values():
        for fact in entry.get('facts', []):
            import re
            for m in re.finditer(r'Q\d+', fact):
                ref_qids.add(m.group())
    return ref_qids

def main():
    # 1. 加载 QID
    qid_list = load_all_qids()
    print(f"加载 {len(qid_list)} 个 QID")
    
    # 2. 加载已有进度
    out_file = WORKDIR / "kb_core_wikidata.json"
    progress_file = WORKDIR / "wikidata_kb_progress.json"
    
    kb = {}
    processed = set()
    
    if out_file.exists():
        with open(out_file) as f:
            kb = json.load(f)
        processed = set(kb.keys())
    
    if progress_file.exists():
        with open(progress_file) as f:
            done = json.load(f)
        processed.update(done)
    
    print(f"已有 {len(kb)} 个实体, 待处理 {len(qid_list) - len(processed)}")
    
    # 3. 批量获取实体
    props = "claims|labels|descriptions"
    total_batches = (len(qid_list) + BATCH - 1) // BATCH
    
    for i in range(0, len(qid_list), BATCH):
        batch = qid_list[i:i+BATCH]
        batch_num = i // BATCH + 1
        
        # 跳过已处理的
        if all(q in processed for q in batch):
            continue
        
        ids = '|'.join(batch)
        data = api({"action": "wbgetentities", "ids": ids, "props": props, "languages": "en"})
        
        if data:
            entities = data.get('entities', {})
            for qid, entity in entities.items():
                if 'missing' in entity:
                    continue
                
                label = entity.get('labels', {}).get('en', {}).get('value', qid)
                desc = entity.get('descriptions', {}).get('en', {}).get('value', '')
                claims = entity.get('claims', {})
                
                facts = []
                if desc:
                    facts.append(f"{label}是{desc}")
                
                target_props = {'P27':'国籍','P106':'职业','P569':'出生','P570':'逝世','P19':'出生地'}
                for pid, pn in target_props.items():
                    if pid in claims:
                        for c in claims[pid][:1]:
                            ms = c.get('mainsnak', {})
                            dv = ms.get('datavalue', {}).get('value', {})
                            dt = ms.get('datatype', '')
                            if dt == 'wikibase-item':
                                vid = dv.get('id', '')
                                facts.append(f"{label}的{pn}是{vid}")
                            elif dt == 'time':
                                t = dv.get('time', '')
                                if t and t.startswith('+'): 
                                    facts.append(f"{label}{pn}于{t[1:11]}")
                
                if facts:
                    kb[qid] = {"name": label, "source": "wikidata", "facts": facts[:6]}
        
        processed.update(batch)
        
        # 定期保存
        if batch_num % 20 == 0:
            with open(out_file, 'w') as f:
                json.dump(kb, f, ensure_ascii=False, indent=2)
            with open(progress_file, 'w') as f:
                json.dump(list(processed), f)
            
            elapsed = batch_num * DELAY
            remaining = (total_batches - batch_num) * DELAY
            print(f"[{batch_num}/{total_batches}] KB: {len(kb)} 实体, ETA {remaining/60:.0f}min")
        
        time.sleep(DELAY)
    
    # 4. 保存最终结果
    with open(out_file, 'w') as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    with open(progress_file, 'w') as f:
        json.dump(list(processed), f)
    
    print(f"\n✅ 实体获取完成: {len(kb)} 实体")
    
    # 5. 解析属性值 QID 为标签
    print("\n解析属性值标签...")
    ref_qids = extract_labels(kb)
    print(f"  需要解析 {len(ref_qids)} 个属性值 QID")
    label_map = resolve_labels(ref_qids)
    print(f"  解析到 {len(label_map)} 个标签")
    
    # 6. 替换 QID 为标签
    for entry in kb.values():
        new_facts = []
        for fact in entry.get('facts', []):
            import re
            def replace_qid(m):
                q = m.group()
                return label_map.get(q, q)
            new_facts.append(re.sub(r'Q\d+', replace_qid, fact))
        entry['facts'] = new_facts
    
    # 7. 最终保存
    with open(out_file, 'w') as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 完成! KB: {len(kb)} 实体")
    print(f"   输出: {out_file}")

if __name__ == '__main__':
    main()
