import math
from shapely.geometry import LineString, Point, Polygon

import main as ps


def road(coords, name='Road', typ='ST'):
    return ps.RoadFeature(LineString(coords), {'ROAD_NAME': name, 'ROAD_TYPE': typ})


def square(size=40.0):
    return Polygon([(0, 0), (size, 0), (size, size), (0, size), (0, 0)])


def test_esri_polygon_with_hole():
    shell = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]]
    g = ps.esri_polygon_to_shape([shell, hole])
    assert g is not None
    assert math.isclose(g.area, 84.0, rel_tol=1e-8)


def test_one_street_frontage():
    p = square()
    roads = [road([(-10, -8), (50, -8)], 'South Road')]
    c = ps.classify_edges_against_roads(p, roads, 12)
    ps._merge_small_boolean_gaps(c)
    fg = ps.contiguous_groups(c, True)
    assert len(fg) == 1
    env, roles, *_ = ps.build_setback_envelope(p, c, 5, 2, 3)
    assert env.area < p.area
    assert sum(1 for x in roles.values() if x == 'street') >= 1
    assert sum(1 for x in roles.values() if x == 'rear') >= 1


def test_two_street_frontages_corner_site():
    p = square()
    roads = [
        road([(-10, -7), (50, -7)], 'South Road'),
        road([(-7, -10), (-7, 50)], 'West Road'),
    ]
    c = ps.classify_edges_against_roads(p, roads, 11)
    ps._merge_small_boolean_gaps(c)
    fg = ps.contiguous_groups(c, True)
    assert len(fg) == 2
    env, roles, *_ = ps.build_setback_envelope(p, c, 5, 2, 3)
    assert env.area > 0
    assert len([r for r in roles.values() if r == 'street']) >= 2


def test_three_street_frontages():
    p = square()
    roads = [
        road([(-10, -7), (50, -7)], 'South'),
        road([(-7, -10), (-7, 50)], 'West'),
        road([(-10, 47), (50, 47)], 'North'),
    ]
    c = ps.classify_edges_against_roads(p, roads, 10)
    ps._merge_small_boolean_gaps(c)
    fg = ps.contiguous_groups(c, True)
    assert len(fg) == 3
    env, roles, *_ = ps.build_setback_envelope(p, c, 4, 2, 3)
    assert env.area > 0
    assert len([r for r in roles.values() if r == 'street']) >= 3


def test_four_street_frontages_all_sides():
    p = square()
    roads = [
        road([(-10, -7), (50, -7)], 'South'),
        road([(-7, -10), (-7, 50)], 'West'),
        road([(-10, 47), (50, 47)], 'North'),
        road([(47, -10), (47, 50)], 'East'),
    ]
    c = ps.classify_edges_against_roads(p, roads, 10)
    ps._merge_small_boolean_gaps(c)
    fg = ps.contiguous_groups(c, True)
    assert len(fg) == 4
    env, roles, frontages, _, rear = ps.build_setback_envelope(p, c, 4, 2, 3)
    assert len(frontages) == 4
    assert rear is None
    assert all(v == 'street' for v in roles.values())
    assert env.area > 0


def test_same_road_name_still_splits_at_true_corner():
    p = square()
    roads = [
        road([(-10, -7), (50, -7)], 'Ring Road'),
        road([(-7, -10), (-7, 50)], 'Ring Road'),
    ]
    c = ps.classify_edges_against_roads(p, roads, 11)
    fg = ps.contiguous_groups(c, True)
    assert len(fg) == 2


def test_segmented_collinear_same_road_remains_one_frontage():
    p = Polygon([(0, 0), (20, 0), (40, 0), (40, 30), (0, 30), (0, 0)])
    roads = [road([(-10, -6), (50, -6)], 'South Road')]
    c = ps.classify_edges_against_roads(p, roads, 10)
    fg = ps.contiguous_groups(c, True)
    assert len(fg) == 1
    assert len(fg[0]) == 2


def test_setbacks_are_measured_from_site_boundary():
    p = square(30)
    roads = [road([(-5, -4), (35, -4)], 'South')]
    c = ps.classify_edges_against_roads(p, roads, 8)
    env, roles, *_ = ps.build_setback_envelope(p, c, 5, 2, 3)
    assert env.bounds[1] >= 4.99


def test_contour_beacon_height_is_nearest_and_marked_screening_basis():
    b = Point(5, 5)
    contours = [
        (LineString([(0, 0), (10, 0)]), {'ELEVATION': 100}),
        (LineString([(0, 10), (10, 10)]), {'ELEVATION': 102}),
    ]
    h, method, dist = ps.beacon_height_from_contours(b, contours)
    assert h in (100.0, 102.0)
    assert method == 'nearest_2m_contour'
    assert math.isclose(dist, 5.0, abs_tol=1e-8)


def test_significant_corners_square_returns_four():
    cs = ps.significant_corners(square())
    assert len(cs) == 4


def test_no_roads_does_not_invent_frontage_or_rear():
    p = square()
    c = ps.classify_edges_against_roads(p, [], 18)
    env, roles, frontages, _, rear = ps.build_setback_envelope(p, c, 5, 2, 3)
    assert frontages == []
    assert rear is None
    assert all(v == 'side' for v in roles.values())
    assert env.area > 0


def test_pdf_generation_has_bytes():
    report = {
        'generated_at': '2026-09-15T00:00:00Z',
        'analysis_id': 'test',
        'input': {'address': 'Test'},
        'location': {'display_name': 'Test', 'lat': -29.8, 'lon': 31.0},
        'parcel': {'area_m2': 1000},
        'zoning': {'attributes': {'ZONING': 'TEST', 'SCHEMENAME': 'TEST'}},
        'frontages': {'count': 1, 'groups': [{'frontage_id': 1, 'length_m': 20, 'road_names': ['Road']}]},
        'buildable_envelope': {'area_m2': 500, 'parcel_area_remaining_pct': 50, 'building_height_m': 18},
        'beacons': {'count': 0, 'items': []},
        'setbacks': {'front_m': 5, 'side_m': 2, 'rear_m': 3, 'basis': 'site boundary'},
        'servitudes': {'intersects': False, 'count': 0},
        'building_footprints': {'coverage_pct': 0},
        'contours': {'min_m': 10, 'max_m': 12},
        'sdf_landuse': {'dominant': None},
        'warnings': [],
        'disclaimer': 'screening only',
    }
    data = ps.generate_pdf(report)
    assert data.startswith(b'%PDF')
    assert len(data) > 1000
