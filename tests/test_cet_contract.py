import copy
import json
import pytest
from cet_scoring import score_band, word_count, length_requirement, validate_report, RUBRIC_VERSIONS
from ai.prompt import build_grading_prompt
from ai.chat_api import ChatCompletionClient, ChatAPIError

def valid_report(score=11):
    return {"score": score, "dimension_feedback": {"content": "任务完整", "language": "表达基本准确", "structure": "衔接清楚"},
            "overall_comment": "论据可以更具体。", "advantages": ["切题"], "disadvantages": ["展开不足"],
            "grammar_errors": [], "sentence_upgrade": []}

@pytest.mark.parametrize("score,band", [(0,"0 分"),(1,"2 分档"),(3,"2 分档"),(4,"5 分档"),(6,"5 分档"),(7,"8 分档"),(9,"8 分档"),(10,"11 分档"),(12,"11 分档"),(13,"14 分档"),(15,"14 分档")])
def test_bands(score,band):
    assert score_band(score)==band

@pytest.mark.parametrize("value", [True,False,None,11.0,11.5,"11","NaN","Infinity",float('nan'),float('inf'),-1,16,[],{}])
def test_bad_score(value):
    with pytest.raises(ValueError): validate_report(valid_report(value))

@pytest.mark.parametrize("field,value", [("dimension_feedback",[]),("dimension_feedback",{"content":1,"language":"a","structure":"b"}),
    ("overall_comment",None),("advantages","a"),("advantages",[{}]),("disadvantages",[True]),
    ("grammar_errors",["a"]),("grammar_errors",[{"sentence":"a","problem":1,"correct":"b"}]),("sentence_upgrade",[{}])])
def test_bad_types(field,value):
    data=valid_report(); data[field]=value
    with pytest.raises(ValueError):validate_report(data)

@pytest.mark.parametrize("field", list(valid_report()))
def test_missing(field):
    data=valid_report(); del data[field]
    with pytest.raises(ValueError):validate_report(data)

@pytest.mark.parametrize("text,count", [("",0),(" \n\t",0),("Don't re-enter well‑known students’ books.",5),("Hello,world!\nNext line.",4),("U.S.A. U.K. AI 2026",4),("中文。 — !",0),("It’s state-of-the-art.",2)])
def test_word_count(text,count):
    assert word_count(text)==count

def test_local_derived_fields():
    data=valid_report(0);data.update(score_band="fabricated",word_count=900)
    result=validate_report(data,15,"One two three.")
    assert result["score"]==0 and result["score_band"]=="0 分" and result["word_count"]==3
    assert data["word_count"]==900

def test_levels_and_topic_lengths():
    assert length_requirement("CET-4")== (120,None)
    assert length_requirement("CET-6")== (150,None)
    assert length_requirement("CET-6","Write 180-220 words")== (180,220)
    assert length_requirement("CET-4","不少于160词")== (160,None)
    assert length_requirement("CET-4","at least 200 words",140)== (140,None)
    assert length_requirement("CET-6","at least 150 words but no more than 200 words")== (150,200)
    assert length_requirement("CET-4","between 120 and 180 words")== (120,180)
    assert length_requirement("CET-6","不少于180个单词，不超过220词")== (180,220)
    assert length_requirement("CET-4","120-180 words",160)== (160,180)
    with pytest.raises(ValueError):length_requirement("CET-4","120-180 words",200)
    for level in ("CET-4","CET-6"):
        prompt=build_grading_prompt(level,"15","at least 180 words","My essay.")[1]["content"]
        assert level in prompt and RUBRIC_VERSIONS[level] in prompt and "180" in prompt
        assert "dimension_feedback" in prompt and "content_score" not in prompt
    assert "论证展开" in build_grading_prompt("CET-6","15","q","text")[1]["content"]

@pytest.mark.parametrize("question,text", [(" ","Text"),("Question","\n \t")])
def test_blank_inputs(question,text):
    with pytest.raises(ValueError):build_grading_prompt("CET-4","15",question,text)

def test_contract_retry_and_raw_report(monkeypatch):
    client=ChatCompletionClient("glm",api_key="fixture")
    replies=iter([json.dumps(valid_report(True)),json.dumps(valid_report(12))])
    captured=[]
    def chat(messages,**kwargs):
        captured.append(copy.deepcopy(messages));return next(replies)
    monkeypatch.setattr(client,"chat",chat)
    result=client.grade_essay(essay_type="CET-4",max_score="15",question="q",student_text="A short essay")
    assert result["score"]==12 and result["word_count"]==3
    assert result["raw_ai_report"]==valid_report(12)
    assert len(result["ai_response_attempts"])==2
    assert "分项之和" not in captured[-1][-1]["content"]

def test_retry_exhausted(monkeypatch):
    client=ChatCompletionClient("glm",api_key="fixture"); calls=[]
    monkeypatch.setattr(client,"chat",lambda *a,**k:calls.append(1) or '{}')
    with pytest.raises(ChatAPIError,match="重试"):client.grade_essay(essay_type="CET-6",max_score="15",question="q",student_text="text")
    assert len(calls)==2
