from app.integrations.geocode import format_coordinates, parse_coordinates


def test_parse_coordinates_with_comma() -> None:
    coords = parse_coordinates("Lat: 38.7223, Lon: -9.1393")
    assert coords == (38.7223, -9.1393)


def test_parse_coordinates_with_space() -> None:
    coords = parse_coordinates("38.7223 -9.1393")
    assert coords == (38.7223, -9.1393)


def test_format_coordinates() -> None:
    assert format_coordinates(38.7223456, -9.1393123) == "38.722346, -9.139312"
