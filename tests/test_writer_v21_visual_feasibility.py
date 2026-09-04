from writer_v21_visual_feasibility import scene_visual_feasibility, visual_feasibility_report

def check(cond,msg):
    if not cond: raise AssertionError(msg)

def main():
    good={"id":1,"voiceover":"Your stomach lining regenerates before acid can destroy it.","search_query":"stomach lining epithelial cells regenerating close up"}
    r=scene_visual_feasibility(good); check(r["showable"],r)
    generic={"id":2,"voiceover":"The cells rebuild constantly.","search_query":"science laboratory footage"}
    r=scene_visual_feasibility(generic); check("generic_visual_wallpaper" in r["warnings"],r)
    abstract={"id":3,"voiceover":"That changes how you see the mountain.","search_query":"reality mystery"}
    r=scene_visual_feasibility(abstract); check("abstract_nonshowable_visual" in r["warnings"],r)
    unrelated={"id":4,"voiceover":"A mantis shrimp accelerates its club underwater.","search_query":"city skyline sunset"}
    r=scene_visual_feasibility(unrelated); check("visual_not_anchored_to_voiceover" in r["warnings"],r)
    report=visual_feasibility_report([good,generic,abstract,unrelated]); check(report["problem_scene_count"]==3,report)
    check(report["problem_scene_ids"]==[2,3,4],report)
    print("writer_v21_visual_feasibility: 6 checks passed")
if __name__=="__main__": main()
