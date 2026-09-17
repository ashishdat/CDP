"""Provenance graph of saved field evidence. No consensus or adjudication."""
import argparse
from collections import Counter
from hashlib import sha256
from itertools import combinations
import json
import math
from pathlib import Path


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def pearson(pairs):
    """Descriptive association only; no independence claim or p-value."""
    if len(pairs) < 2:
        return None
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    xx = sum((x-mx)**2 for x in xs)
    yy = sum((y-my)**2 for y in ys)
    if xx == 0 or yy == 0:
        return None
    return sum((x-mx)*(y-my) for x, y in pairs) / math.sqrt(xx*yy)


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class EvidenceGraph:
    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.confidences = []
        self.fields = []
        self.samples = []
        self.agreements = []
        self._identities = set()

    def node(self, kind, channel, document, page, source, pointer, payload, parents=()):
        identity = digest([kind, document, page, source, pointer])
        node = {"id": identity, "type": "EvidenceNode", "kind": kind,
                "channel": channel, "document_id": document, "page_number": page,
                "source": source, "json_pointer": pointer, "observation": payload}
        if identity in self.nodes and self.nodes[identity] != node:
            raise ValueError("Conflicting evidence identity")
        self.nodes[identity] = node
        for parent in parents:
            self.edge(identity, parent, "DERIVED_FROM")
        return identity

    def edge(self, start, end, relation):
        key = digest([start, end, relation])
        self.edges[key] = {"id": key, "type": "EvidenceEdge", "from": start,
                           "to": end, "relation": relation}

    def confidence(self, node, metric, value, basis):
        self.confidences.append({"type": "EvidenceConfidence", "node_id": node,
            "metric": metric, "value": value if numeric(value) else None,
            "availability": "RECORDED" if numeric(value) else "NOT_RECORDED",
            "basis": basis, "calibrated": metric == "calibrated_confidence"})

    def read(self, path, expected=None):
        path = Path(path)
        content = path.read_bytes()
        checksum = sha256(content).hexdigest()
        if expected and checksum != expected:
            raise ValueError("Artifact hash mismatch")
        return json.loads(content), {"path": str(path), "sha256": checksum}

    def add_extraction(self, path):
        extraction, es = self.read(path)
        if extraction.get("type") != "ExtractionResult" or extraction.get("status") != "ASSEMBLED":
            raise ValueError("Assembled ExtractionResult required")
        doc, page = extraction["document"]["document_id"], extraction["page"]["page_number"]
        if (doc, page) in self._identities:
            raise ValueError("Duplicate document/page")
        self._identities.add((doc, page))
        names = [f["field_name"] for f in extraction["field_results"]]
        if not names or len(set(names)) != len(names):
            raise ValueError("Unique nonempty fields required")
        artifacts = {}
        for key, ref in extraction["source_artifacts"].items():
            artifacts[key] = self.read(ref["path"], ref["sha256"])
        geometry, gs = artifacts["geometry"]
        if geometry["page_number"] != page or geometry["status"] != "SUCCESS":
            raise ValueError("Geometry page/status mismatch")
        app, aps = self.read(Path(path).parent.parent / "ApplicationResult.json")
        if app["outputs"]["classification"]["document_id"] != doc:
            raise ValueError("Application document mismatch")
        reg = app["outputs"]["registration"]
        if reg.get("page_number") != page or reg.get("status") != "SUCCESS":
            raise ValueError("Registration lineage mismatch")
        decision, ds = self.read(Path(path).parent.parent / "DecisionResult.json")
        if (decision.get("extraction_reference", {}).get("sha256") != es["sha256"]
                or decision["document"] != extraction["document"]
                or decision["page"] != extraction["page"]
                or decision["extracted_fields"] != extraction["field_results"]):
            raise ValueError("Decision lineage mismatch")
        root = self.node("SOURCE", "Source Page", doc, page,
            {"document_sha256": doc}, "/pages/"+str(page),
            {"meaning": "Shared source TIFF page, not an independent truth label"})
        shared = []
        for key, value in reg.items():
            if key in {"selection", "evidence", "telemetry_reference"}:
                continue
            shared.append(self.node("OBSERVATION", "Registration", doc, page, aps,
                "/outputs/registration/"+key, value, [root]))
        reg_nodes = []
        for key, value in reg.get("evidence", {}).items():
            n = self.node("OBSERVATION", "Registration", doc, page, aps,
                "/outputs/registration/evidence/"+key, value, [root])
            reg_nodes.append(n)
            if key in {"alignment_confidence", "homography_quality"}:
                self.confidence(n, key, value, "Recorded registration metric; not field accuracy")
        shared.extend(reg_nodes)
        for i, c in enumerate(reg["selection"]["candidate_templates"]):
            if c["page_number"] != page or c["template_id"] != reg["template_id"]:
                continue
            pointer = f"/outputs/registration/selection/candidate_templates/{i}"
            d = c["diagnostics"]
            for j, phrase in enumerate(d["expected_anchors"]):
                shared.append(self.node("OBSERVATION", "Template", doc, page, aps,
                    pointer+f"/diagnostics/expected_anchors/{j}",
                    {"phrase": phrase, "detected": phrase in d["matched_anchor_phrases"],
                     "missing_required": phrase in d["missing_required_anchors"],
                     "template_id": c["template_id"], "template_version": c["template_version"]}, [root]))
            for key, value in c["scores"].items():
                n = self.node("OBSERVATION", "Template", doc, page, aps,
                    pointer+"/scores/"+key, value, [root])
                shared.append(n)
                self.confidence(n, key, value, "Recorded template score; not independent field evidence")
        geometry_rows = {r["field"]: (i,r["result"]) for i,r in enumerate(geometry["fields"])}
        field_links = {}
        normalized_nodes = {}
        for index, f in enumerate(extraction["field_results"]):
            name = f["field_name"]
            fp = f"/field_results/{index}"
            field_id = self.node("FIELD", "Field", doc, page, es, fp, {"field_name":name})
            linked = list(shared)
            gi, g = geometry_rows[name]
            geom_nodes = []
            for key,value in g.items():
                parts = list(enumerate(value)) if isinstance(value,list) else [(None,value)]
                for j, part in parts:
                    pointer = f"/fields/{gi}/result/{key}"+(f"/{j}" if j is not None else "")
                    geom_nodes.append(self.node("OBSERVATION", "Geometry", doc,page,gs,pointer,part,[root]+reg_nodes))
            linked.extend(geom_nodes)
            geometry_conf = self.node("AVAILABILITY", "Geometry",doc,page,es,fp+"/geometry_confidence",
                {"status":"NOT_RECORDED","note":"Geometry success is not a numeric confidence"})
            linked.append(geometry_conf)
            self.confidence(geometry_conf,"geometry_confidence",None,"No numeric geometry confidence in saved contract")
            ocr_ids = {}
            for j,c in enumerate(f["ocr"]["candidates"]):
                n = self.node("OBSERVATION","OCR",doc,page,es,fp+f"/ocr/candidates/{j}",c,[root]+geom_nodes)
                ocr_ids[f"{name}:{j}"] = n
                linked.append(n)
                for key in ("raw_confidence","calibrated_confidence"):
                    self.confidence(n,key,c.get(key),"Saved provider observation; no recalibration")
            validator_ids = {}
            for j,v in enumerate(f["candidate_validations"]):
                if v["field_id"] != name or v["candidate_id"] not in ocr_ids:
                    raise ValueError("Validator candidate lineage mismatch")
                n = self.node("OBSERVATION","Validator",doc,page,es,fp+f"/candidate_validations/{j}",v,[ocr_ids[v["candidate_id"]]])
                validator_ids[v["candidate_id"]] = n
                linked.append(n)
            winner = f["ranked_candidate"]
            normalized = self.node("DERIVED_VALUE","Selected Value",doc,page,es,fp+"/normalized_value",f["normalized_value"],
                [validator_ids[winner["candidate_id"]]] if winner else [root])
            normalized_nodes[name] = normalized
            linked.append(normalized)
            if winner:
                if winner["ocr_candidate"] != self.nodes[ocr_ids[winner["candidate_id"]]]["observation"]:
                    raise ValueError("Winner OCR mismatch")
                n = self.node("OBSERVATION","Ranking",doc,page,es,fp+"/ranked_candidate",winner,list(ocr_ids.values()))
                linked.append(n)
                raw = winner["ocr_candidate"].get("raw_confidence")
                rc = reg.get("evidence",{}).get("alignment_confidence")
                if numeric(raw) and numeric(rc):
                    self.samples.append({"document_id":doc,"field_name":name,"ocr_confidence":raw,"registration_confidence":rc})
            for va,vb in combinations(f["candidate_validations"],2):
                if va["normalized_value"] is None or vb["normalized_value"] is None:
                    continue
                self.agreements.append({"document_id":doc,"page":page,"field_name":name,
                    "left_node":validator_ids[va["candidate_id"]],"right_node":validator_ids[vb["candidate_id"]],
                    "agreement":va["normalized_value"]==vb["normalized_value"],
                    "basis":"Exact equality of saved normalized values; no voting or new normalization"})
            for j,r in enumerate(f.get("alternatives",[])):
                linked.append(self.node("OBSERVATION","Ranking",doc,page,es,fp+f"/alternatives/{j}",r,list(ocr_ids.values())))
            field_links[name] = (field_id,linked)
        # Link checks to the complete claim input, since existing deterministic
        # checks can use claim_values. This records dependence, not agreement.
        for name,check in decision.get("deterministic_checks",{}).items():
            if name not in field_links:
                raise ValueError("Unknown rule field")
            for key,value in check.items():
                parts = list(enumerate(value)) if isinstance(value,list) else [(None,value)]
                for j,part in parts:
                    n=self.node("OBSERVATION","Business Rule",doc,page,ds,
                        "/deterministic_checks/"+name+"/"+key+(f"/{j}" if j is not None else ""),part,list(normalized_nodes.values()))
                    field_links[name][1].append(n)
        for group in ("evidence_items","contradictions"):
            for i,item in enumerate(decision.get("claim_facts",{}).get(group,[])):
                names_for_item=item.get("metadata",{}).get("supported_fields",[])
                linked_names=[n for n in names_for_item if n in field_links]
                parents=[normalized_nodes[n] for n in linked_names] or list(normalized_nodes.values())
                n=self.node("OBSERVATION","Cross Field",doc,page,ds,f"/claim_facts/{group}/{i}",item,parents)
                for name in linked_names:
                    field_links[name][1].append(n)
        for i,fd in enumerate(decision.get("field_decisions",[])):
            name=fd["field_name"]
            if name not in field_links:
                raise ValueError("Unknown decision field")
            n=self.node("OBSERVATION","Business Rule",doc,page,ds,f"/field_decisions/{i}",
                {k:v for k,v in fd.items() if k not in {"supporting_evidence","conflicting_evidence"}},list(normalized_nodes.values()))
            field_links[name][1].append(n)
            self.confidence(n,"recorded_policy_probability",fd.get("calibrated_probability"),"Saved decision output; dependent on upstream evidence")
            for group in ("supporting_evidence","conflicting_evidence"):
                for j,item in enumerate(fd.get(group,[])):
                    child=self.node("OBSERVATION","Business Rule",doc,page,ds,f"/field_decisions/{i}/{group}/{j}",item,list(normalized_nodes.values()))
                    field_links[name][1].append(child)
                    self.edge(n,child,"USES")
        for name,(field_id,linked) in field_links.items():
            channels={self.nodes[n]["channel"] for n in linked if self.nodes[n]["kind"]=="OBSERVATION"}
            missing=[c for c in ("OCR","Geometry","Registration","Template","Cross Field","Historical Pattern","Validator","Business Rule") if c not in channels]
            for n in set(linked):
                self.edge(field_id,n,"HAS_EVIDENCE")
            self.fields.append({"field_node":field_id,"field_name":name,"document_id":doc,"page_number":page,
                "evidence_nodes":sorted(set(linked)),"missing_sources":missing,"source_page_node":root})

    def report(self):
        if any(e["from"] not in self.nodes or e["to"] not in self.nodes for e in self.edges.values()):
            raise ValueError("Dangling edge")
        parents = {}
        for edge in self.edges.values():
            if edge["relation"] in {"DERIVED_FROM", "USES"}:
                parents.setdefault(edge["from"], []).append(edge["to"])
        cache = {}
        def roots(node, visiting):
            if node in cache:
                return cache[node]
            if node in visiting:
                raise ValueError("Cyclic provenance")
            found = {node} if self.nodes[node]["kind"] == "SOURCE" else set()
            for parent in parents.get(node, []):
                found.update(roots(parent, visiting | {node}))
            cache[node] = found
            return found
        pairs=0
        for f in self.fields:
            observed=[n for n in f["evidence_nodes"] if self.nodes[n]["kind"]=="OBSERVATION"]
            if any(f["source_page_node"] not in roots(n, set()) for n in observed):
                raise ValueError("Observation lacks recorded source-page ancestry")
            pairs+=len(observed)*(len(observed)-1)//2
        correlations=[]
        for name in sorted({s["field_name"] for s in self.samples}):
            selected=[s for s in self.samples if s["field_name"]==name]
            correlations.append({"field_name":name,"n_documents":len(selected),
                "channels":["winning OCR raw confidence","registration alignment confidence"],
                "pearson_r":pearson([(s["ocr_confidence"],s["registration_confidence"]) for s in selected]),
                "null_reason":"Insufficient observations or zero variance" if len(selected)<2 or pearson([(s["ocr_confidence"],s["registration_confidence"]) for s in selected]) is None else None})
        agree=sum(p["agreement"] for p in self.agreements)
        return {"type":"EvidenceGraph","version":1,"EvidenceNode":list(self.nodes.values()),
            "EvidenceEdge":list(self.edges.values()),"EvidenceConfidence":self.confidences,
            "fields":self.fields,"metrics":{"documents":len(self._identities),"fields":len(self.fields),
                "nodes":len(self.nodes),"edges":len(self.edges),
                "missing_source_fields":dict(Counter(k for f in self.fields for k in f["missing_sources"])),
                "evidence_independence":{"within_field_observation_pairs":pairs,
                    "pairs_sharing_source_page":pairs,"proven_independent_pairs":0,
                    "statistical_independence":None,
                    "meaning":"All represented measurements/checks derive from the same source page per claim; separate nodes do not establish independent corroboration."},
                "correlation":correlations,
                "agreement":{"comparable_candidate_pairs":len(self.agreements),"agreeing_pairs":agree,
                    "disagreeing_pairs":len(self.agreements)-agree,
                    "agreement_percent":100*agree/len(self.agreements) if self.agreements else None,
                    "basis":"Within-field candidate normalized-value equality only. Different quantities (layout/confidence/validity) are not equated. No independent pairs are asserted."}},
            "correlation_observations":self.samples,"agreement_observations":self.agreements,
            "limitations":["No evidence votes, consensus status, or combined confidence generated.",
                "Shared page ancestry demonstrates common inputs, not measured statistical dependence or causation.",
                "Correlation is descriptive across documents for each field name; null means unmeasurable, not zero.",
                "Historical patterns are absent. Missing sources are inventory entries, not fabricated evidence nodes.",
                "Template observations describe existing hypotheses, not human-verified form identities.",
                "No runtime stage, LLM, or adjudicator was executed."]}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extractions",nargs="+")
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    graph=EvidenceGraph()
    for path in args.extractions:
        graph.add_extraction(path)
    text=json.dumps(graph.report(),indent=2,allow_nan=False)+"\n"
    with Path(args.output).open("x",encoding="utf-8") as stream:
        stream.write(text)
