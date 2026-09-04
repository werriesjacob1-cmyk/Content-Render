#!/usr/bin/env python3
"""Zero-network regressions for molecular_media.py."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import molecular_media as M


def check(cond,label):
    if not cond: raise AssertionError(label)
    print(f"PASS {label}")


SAMPLE={
    "entry":{"id":"4HHB"},
    "struct":{"title":"THE CRYSTAL STRUCTURE OF HUMAN DEOXYHAEMOGLOBIN"},
    "exptl":[{"method":"X-RAY DIFFRACTION"}],
    "citation":[{
        "id":"primary","rcsb_is_primary":"Y","title":"The crystal structure of human deoxyhaemoglobin at 1.74 A resolution",
        "rcsb_authors":["Fermi, G.","Perutz, M.F.","Shaanan, B.","Fourme, R."],"year":1984,
        "pdbx_database_id_DOI":"10.1016/0022-2836(84)90472-8"
    }],
    "database_2":[{"database_id":"PDB","pdbx_DOI":"10.2210/pdb4hhb/pdb"}],
    "pdbx_audit_revision_history":[{"revision_date":"1984-07-17T00:00:00.000+00:00"},{"revision_date":"2026-08-12T00:00:00.000+00:00"}],
}


def test_entry_metadata_and_rights():
    e=M.parse_entry(SAMPLE,"4hhb")
    check(e.pdb_id=="4HHB","PDB ID normalized")
    check(e.experimental_methods==("X-RAY DIFFRACTION",),"experimental method preserved")
    check(e.primary_citation_year==1984 and "Fermi" in e.attribution(),"primary citation drives attribution")
    check(e.pdb_doi=="10.2210/pdb4hhb/pdb","PDB DOI preserved")
    check(e.latest_revision_date.startswith("2026-08-12"),"latest revision preserved")
    check(e.license_name=="CC0-1.0" and e.public_domain,"core PDB data marked with verified CC0 rights")
    check(e.production_eligible is False,"authentic structure candidate is not auto-promoted")
    recipe=e.render_recipe()
    check(recipe["viewer"]=="molstar_preferred" and recipe["vision_qa_required"] is True,"render recipe prefers Mol* and still requires QA")
    check(recipe["coordinate_url"].endswith("/4HHB.cif"),"recipe points to authentic coordinate file")


def test_search_contract_without_network():
    captured={}
    old=M._json_request
    def fake(url,payload=None,timeout=30):
        captured.update(url=url,payload=payload)
        return {"result_set":[{"identifier":"4HHB","score":1.0},{"identifier":"1BNA","score":0.7}]}
    M._json_request=fake
    try:
        hits=M.search_rcsb("human hemoglobin",2)
    finally:
        M._json_request=old
    check(captured["url"]=="https://search.rcsb.org/rcsbsearch/v2/query","current RCSB Search API endpoint used")
    q=captured["payload"]["query"]
    check(q["service"]=="full_text" and q["parameters"]["value"]=="human hemoglobin","full-text query contract correct")
    opts=captured["payload"]["request_options"]
    check(opts["results_content_type"]==["experimental"],"computed models excluded from authentic experimental search")
    check([h.pdb_id for h in hits]==["4HHB","1BNA"],"search hits normalized and ordered")


def test_fetch_entry_contract():
    captured={}
    old=M._json_request
    def fake(url,payload=None,timeout=30): captured["url"]=url; return SAMPLE
    M._json_request=fake
    try: e=M.fetch_entry("4hhb")
    finally: M._json_request=old
    check(captured["url"].endswith("/core/entry/4HHB"),"Data API fetch uses exact normalized entry ID")
    check(e.pdb_id=="4HHB","fetched entry parsed")


def test_coordinate_validation_without_network():
    cif=("data_4HHB\n#\nloop_\n_atom_site.group_PDB\n_atom_site.id\nATOM 1\n"+"# filler\n"*100).encode()
    class Resp:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def read(self): return cif
    old=M.urllib.request.urlopen
    M.urllib.request.urlopen=lambda req,timeout=60: Resp()
    try:
        with tempfile.TemporaryDirectory() as td:
            dest=os.path.join(td,"4HHB.cif")
            got=M.download_coordinates(M.parse_entry(SAMPLE,"4HHB"),dest)
            check(os.path.exists(got) and os.path.getsize(got)>500,"validated coordinate data written")
    finally: M.urllib.request.urlopen=old

    bad=("data_1BNA\n_atom_site.id\n"+"x"*600).encode()
    class BadResp(Resp):
        def read(self): return bad
    M.urllib.request.urlopen=lambda req,timeout=60: BadResp()
    try:
        with tempfile.TemporaryDirectory() as td:
            try:
                M.download_coordinates(M.parse_entry(SAMPLE,"4HHB"),os.path.join(td,"bad.cif"))
                raise AssertionError("wrong structure should fail")
            except M.MolecularMediaError:
                check(True,"coordinate identity mismatch fails closed")
    finally: M.urllib.request.urlopen=old


def test_id_guards():
    check(M.normalize_pdb_id("4hhb")=="4HHB","lowercase current PDB ID accepted")
    for bad in ("", "HHB", "12345", "../../x"):
        try:
            M.normalize_pdb_id(bad); raise AssertionError("invalid ID should fail")
        except ValueError: pass
    check(True,"invalid/path-like PDB IDs rejected")


if __name__=="__main__":
    test_entry_metadata_and_rights(); test_search_contract_without_network(); test_fetch_entry_contract(); test_coordinate_validation_without_network(); test_id_guards()
    print("molecular_media tests: PASS")
