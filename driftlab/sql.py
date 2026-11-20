"""Compile the same logical operations into safely bound dialect SQL."""
def quote(name):
    return '"' + name.replace('"', '""') + '"'


def schema(case, engine):
    statements = []
    for table in case['tables']:
        columns = []
        for col in table['columns']:
            kind = 'DOUBLE PRECISION' if engine == 'postgres' and col['type'] == 'REAL' else col['type']
            if engine == 'sqlite' and col['type'] == 'JSON':
                kind = 'TEXT'
            item = quote(col['name']) + ' ' + kind
            if col['primary_key']:
                item += ' PRIMARY KEY'
            if not col['nullable']:
                item += ' NOT NULL'
            if col['unique']:
                item += ' UNIQUE'
            if engine == 'sqlite' and col['type'] == 'JSON':
                item += ' CHECK (' + quote(col['name']) + ' IS NULL OR json_valid(' + quote(col['name']) + '))'
            if col.get('references'):
                ref = col['references']
                item += ' REFERENCES ' + quote(ref['table']) + '(' + quote(ref['column']) + ')'
            columns.append(item)
        suffix = ' STRICT' if engine == 'sqlite' and case['sqlite']['strict'] else ''
        statements.append('CREATE TABLE ' + quote(table['name']) + ' (' + ', '.join(columns) + ')' + suffix)
    return statements


def operation(op, engine):
    marker = '%s' if engine == 'postgres' else '?'
    params = []
    table = quote(op['table'])
    kind = op['type']
    if kind == 'insert':
        keys = list(op['values'])
        params.extend(op['values'].values())
        return 'INSERT INTO ' + table + ' (' + ', '.join(map(quote, keys)) + ') VALUES (' + ', '.join([marker] * len(keys)) + ')', params
    if kind == 'select':
        statement = 'SELECT ' + ', '.join(map(quote, op['columns'])) + ' FROM ' + table
    elif kind == 'update':
        statement = 'UPDATE ' + table + ' SET ' + ', '.join(quote(k) + '=' + marker for k in op['values'])
        params.extend(op['values'].values())
    else:
        statement = 'DELETE FROM ' + table
    predicates = []
    operators = {'eq': '=', 'ne': '<>', 'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<=', 'like': 'LIKE'}
    for term in op.get('where', []):
        column = quote(term['column'])
        if term['op'] == 'json_array_text_contains':
            # Path keys are validated identifiers; values remain bound parameters.
            if engine == 'sqlite':
                path = '$.' + '.'.join(term['path'])
                expression = "json_extract(drift_message.value, '$." + term['field'] + "')"
                source = "json_each(" + column + ", '" + path + "')"
            else:
                source_value = column + ''.join("->'" + key + "'" for key in term['path'])
                source = 'json_array_elements(' + source_value + ')'
                expression = "drift_message.value->>'" + term['field'] + "'"
            predicates.append('EXISTS (SELECT 1 FROM ' + source + ' AS drift_message WHERE LOWER('
                              + expression + ') LIKE ' + marker + ')')
            params.append('%' + term['value'].lower() + '%')
        elif term['op'] in ('is_null', 'not_null'):
            predicates.append(column + (' IS NULL' if term['op'] == 'is_null' else ' IS NOT NULL'))
        else:
            predicates.append(column + ' ' + operators[term['op']] + ' ' + marker)
            params.append(term['value'])
    if predicates:
        statement += ' WHERE ' + ' AND '.join(predicates)
    if kind == 'select':
        ordering = []
        for term in op['order_by']:
            text = quote(term['column']) + ' ' + term['direction'].upper()
            if 'nulls' in term:
                text += ' NULLS ' + term['nulls'].upper()
            ordering.append(text)
        if ordering:
            statement += ' ORDER BY ' + ', '.join(ordering)
        if 'limit' in op:
            statement += ' LIMIT ' + marker
            params.append(op['limit'])
    return statement, params


def seed(row):
    return {'id': row['id'], 'type': 'insert', 'table': row['table'], 'values': row['values']}
