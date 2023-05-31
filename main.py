from typing import Callable, Dict, List, Tuple, Union
from lxml import html, etree

Knot = Dict[str, Union[str, int]]
Path = List[Knot]

Options = {
    'root': html.Element,
    'id_name': Callable[[str], bool],
    'class_name': Callable[[str], bool],
    'tag_name': Callable[[str], bool],
    'attr': Callable[[str, str], bool],
    'seed_min_length': int,
    'optimized_min_length': int,
    'threshold': int,
    'max_number_of_tries': int,
}

config: Options
root_document: html.Element


def finder(input: html.Element, options: Options = None) -> str:
    if input.tag == 'html':
        return 'html'
    defaults: Options = {
        'root': input.getroottree().getroot(),
        'id_name': lambda name: True,
        'class_name': lambda name: True,
        'tag_name': lambda name: True,
        'attr': lambda name, value: False,
        'seed_min_length': 1,
        'optimized_min_length': 2,
        'threshold': 1000,
        'max_number_of_tries': 10000,
    }

    global config, root_document
    config = {**defaults, **(options or {})}
    root_document = config['root']

    path = (
            bottom_up_search(input, 'all')
            or bottom_up_search(input, 'two')
            or bottom_up_search(input, 'one')
            or bottom_up_search(input, 'none')
    )

    if path:
        optimized = sort(optimize(path, input))
        if optimized:
            path = optimized[0]
        return selector(path)
    else:
        raise ValueError('Selector was not found.')


def bottom_up_search(input: html.Element, limit: str) -> Union[Path, None]:
    path: Union[Path, None] = None
    stack: List[List[Knot]] = []
    current: html.Element = input
    i = 0
    while current is not None:
        # Check if the current element is a comment
        if isinstance(current, etree._Comment):
            current = current.getparent()
            i += 1
            continue

        level: List[Knot] = (
                maybe(id(current))
                or maybe(*attr(current))
                or maybe(*class_names(current))
                or maybe(tag_name(current))
                or [any()]
        )
        nth = index(current)
        if limit == 'all':
            if nth:
                level = level + [nth_child(node, nth) for node in level if dispensable_nth(node)]
        elif limit == 'two':
            level = level[:1]
            if nth:
                level = level + [nth_child(level[0], nth)]
        elif limit == 'one':
            level = level[:1]
            if nth and dispensable_nth(level[0]):
                level = [nth_child(level[0], nth)]
        elif limit == 'none':
            level = [any()]
            if nth:
                level = [nth_child(level[0], nth)]

        for node in level:
            node['level'] = i
        stack.append(level)

        if len(stack) >= config['seed_min_length']:
            path = find_unique_path(stack)
            if path:
                break

        current = current.getparent()
        i += 1

    if not path:
        path = find_unique_path(stack)
    return path


def find_unique_path(stack: List[List[Knot]]) -> Union[Path, None]:
    paths = sort(combinations(stack))
    if len(paths) > config['threshold']:
        return None
    for candidate in paths:
        if unique(candidate):
            return candidate
    return None


def selector(path: Path) -> str:
    node = path[0]
    query = node['name']
    for i in range(1, len(path)):
        level = path[i]['level'] or 0
        if node['level'] == level - 1:
            query = f'{path[i]["name"]} > {query}'
        else:
            query = f'{path[i]["name"]} {query}'
        node = path[i]
    return query


def penalty(path: Path) -> int:
    return sum(node['penalty'] for node in path)


def unique(path: Path) -> bool:
    css = selector(path)
    elements = root_document.cssselect(css)
    if len(elements) == 0:
        raise ValueError(f"Can't select any node with this selector: {css}")
    return len(elements) == 1


def id(input: html.Element) -> Union[Knot, None]:
    element_id = input.get('id')
    if element_id and config['id_name'](element_id):
        return {'name': '#' + css_escape(element_id, is_identifier=True), 'penalty': 0, 'level': 0}
    return None


def attr(input: html.Element) -> List[Knot]:
    attrs = [
        (attr[0], attr[1])
        for attr in input.items()
        if config['attr'](attr[0], attr[1])
    ]
    return [
        {
            'name': f'[{css_escape(attr[0], is_identifier=True)}="{css_escape(attr[1])}"]',
            'penalty': 0.5,
            'level': 0,
        }
        for attr in attrs
    ]


def class_names(input: html.Element) -> List[Knot]:
    names = (input.get('class') or '').split()
    return [
        {'name': '.' + css_escape(name, is_identifier=True), 'penalty': 1, 'level': 0}
        for name in names
        if config['class_name'](name)
    ]


def tag_name(input: html.Element) -> Knot:
    name = input.tag
    if config['tag_name'](name):
        return {'name': name, 'penalty': 2, 'level': 0}
    return None


def any() -> Knot:
    return {'name': '*', 'penalty': 3, 'level': 0}


def index(input: html.Element) -> Union[int, None]:
    parent = input.getparent()
    if parent is None:
        return None
    i = 0
    for child in parent:
        if child == input:
            return i + 1
        i += 1
    return None


def nth_child(node: Knot, i: int) -> Knot:
    return {'name': node['name'] + f':nth-child({i})', 'penalty': node['penalty'] + 1, 'level': node['level']}


def dispensable_nth(node: Knot) -> bool:
    return node['name'] != 'html' and not node['name'].startswith('#')


def maybe(*level: Union[Knot, None]) -> Union[List[Knot], None]:
    list_ = [item for item in level if item is not None]
    if list_:
        return list_
    return None


def combinations(stack: List[List[Knot]], path: Path = []) -> List[Path]:
    if stack:
        result = []
        for node in stack[0]:
            result.extend(combinations(stack[1:], path + [node]))
        return result
    return [path]


def sort(paths: List[Path]) -> List[Path]:
    return sorted(paths, key=penalty)


def optimize(path: Path, input: html.Element, scope: dict = None) -> List[Path]:
    if scope is None:
        scope = {'counter': 0, 'visited': {}}

    if len(path) > 2 and len(path) > config['optimized_min_length']:
        results = []
        for i in range(1, len(path) - 1):
            if scope['counter'] > config['max_number_of_tries']:
                return results

            scope['counter'] += 1
            new_path = path[:i] + path[i + 1:]
            new_path_key = selector(new_path)

            if new_path_key in scope['visited']:
                continue

            if unique(new_path) and same(new_path, input):
                results.append(new_path)
                scope['visited'][new_path_key] = True
                results.extend(optimize(new_path, input, scope))

        return results
    return []


def same(path: Path, input: html.Element) -> bool:
    return root_document.cssselect(selector(path))[0] == input


def css_escape(string: str, is_identifier: bool = False) -> str:
    # This function is a simplified version of the cssesc JavaScript library.
    # More complete conversion can be done with the cssselect library. However,
    # cssselect does not support the 'is_identifier' option.
    output = ''
    for char in string:
        code_point = ord(char)
        if 0x20 <= code_point <= 0x7E:
            output += char
        else:
            output += f'\\{code_point:04X} '
    return output


if __name__ == "__main__":
    import requests
    from lxml import html as lxml_html

    html_doc = lxml_html.fromstring(requests.get("https://example.com/").text)

    print(finder(html_doc[1][2]))