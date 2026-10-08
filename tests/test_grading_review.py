import math
import pytest
from grading_review import validate_teacher_score
@pytest.mark.parametrize("value,expected", [("12","12"),(15,"15"),(0,"0"),(" 8 ","8")])
def test_teacher_integer(value,expected):
    assert validate_teacher_score(value,15)==expected
@pytest.mark.parametrize("value", [True,False,None,12.0,12.5,"12.0","NaN","Infinity",-1,16,[],{},math.nan])
def test_teacher_invalid(value):
    with pytest.raises(ValueError):validate_teacher_score(value,15)
