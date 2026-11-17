{# Lê arquivos JSON Lines da pasta de dados com colunas declaradas, para o tipo não depender do conteúdo. #}
{% macro read_jsonl(pattern, columns, with_source=false) -%}
  read_json(
    '{{ var("data_dir") }}/{{ pattern }}',
    format = 'newline_delimited',
    columns = {
      {%- for name, kind in columns.items() %}
      '{{ name }}': '{{ kind }}'{{ "," if not loop.last }}
      {%- endfor %}
    }
    {%- if with_source %}, filename = true{% endif %}
  )
{%- endmacro %}

{# A pasta da fonte dentro de data/bronze, tirada do caminho do arquivo. #}
{% macro source_from_filename() -%}
  regexp_extract(replace(filename, '\', '/'), '/bronze/([^/]+)/[^/]+$', 1)
{%- endmacro %}

{# Texto ISO com Z, usado nas tabelas exportadas. #}
{% macro iso(column) -%}
  strftime({{ column }}, '%Y-%m-%dT%H:%M:%SZ')
{%- endmacro %}
