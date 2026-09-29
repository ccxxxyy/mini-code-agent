import math

import pytest

from geometry import Circle, Rectangle, total_area


def test_circle_area():
    assert math.isclose(Circle(2.0).area(), math.pi * 4)


def test_rectangle_area():
    assert Rectangle(3.0, 4.0).area() == 12.0


def test_total_area_mixed():
    shapes = [Circle(1.0), Rectangle(2.0, 3.0)]
    assert math.isclose(total_area(shapes), math.pi + 6.0)


def test_negative_dimension_rejected():
    with pytest.raises(ValueError):
        Rectangle(-1.0, 2.0)
