import streamlit as st
import xml.etree.ElementTree as ET
import sqlparse
import re
from xml.dom import minidom
from io import StringIO

# --- Global Constants ---
TYPE_MAPPING = {
    'String': 'VARCHAR(255)',
    'Integer': 'INT',
    'Boolean': 'BOOLEAN',
    'Float': 'FLOAT',
    'Double': 'DOUBLE',
    'Long': 'BIGINT',
    'Date': 'DATE',
}

XMI_NAMESPACE = "http://schema.omg.org/spec/XMI/2.1"
UML_NAMESPACE = "http://www.eclipse.org/uml2/3.0.0/UML"

def get_attrib(elem, attrib_name):
    return elem.attrib.get(f'{{{XMI_NAMESPACE}}}{attrib_name}') or elem.attrib.get(attrib_name)

# --- UML to SQL Script (Original) ---
class UMLParser:
    def __init__(self, xml_content):
        self.tree = ET.ElementTree(ET.fromstring(xml_content))
        self.root = self.tree.getroot()

        self.class_ids = {}
        self.classes = {}
        self.associations = []

    def parse_classes(self):
        for elem in self.root.iter():
            if elem.tag.endswith("packagedElement"):
                type_attr = get_attrib(elem, 'type')
                if type_attr == 'uml:Class':
                    class_id = get_attrib(elem, 'id')
                    class_name = elem.attrib.get('name')
                    if not class_id or not class_name:
                        continue
                    self.class_ids[class_id] = class_name

                    attrs = []
                    for attr in elem.findall('ownedAttribute'):
                        attr_name = attr.attrib.get('name')
                        attr_type = attr.attrib.get('type')
                        sql_type = TYPE_MAPPING.get(attr_type, 'VARCHAR(255)') if attr_type else 'VARCHAR(255)'
                        if attr_name:
                            attrs.append((attr_name, sql_type))
                    if not any(a[0].lower() == 'id' for a in attrs):
                        attrs.insert(0, ('id', 'INT PRIMARY KEY'))
                    else:
                        new_attrs = []
                        for a_name, a_type in attrs:
                            if a_name.lower() == 'id' and 'primary key' not in a_type.lower():
                                new_attrs.append((a_name, f"{a_type} PRIMARY KEY"))
                            else:
                                new_attrs.append((a_name, a_type))
                        attrs = new_attrs
                    self.classes[class_name] = attrs

    def parse_associations(self):
        for elem in self.root.iter():
            if elem.tag.endswith("packagedElement"):
                type_attr = get_attrib(elem, 'type')
                if type_attr == 'uml:Association':
                    ends = elem.findall('ownedEnd')
                    if len(ends) != 2:
                        continue

                    e1, e2 = ends

                    type1 = e1.attrib.get('type')
                    name1 = e1.attrib.get('name') or 'ref1'
                    lower1 = int(e1.attrib.get('lower', '0'))
                    upper1_raw = e1.attrib.get('upper', '1')
                    upper1 = int(upper1_raw) if upper1_raw.isdigit() else -1

                    type2 = e2.attrib.get('type')
                    name2 = e2.attrib.get('name') or 'ref2'
                    lower2 = int(e2.attrib.get('lower', '0'))
                    upper2_raw = e2.attrib.get('upper', '1')
                    upper2 = int(upper2_raw) if upper2_raw.isdigit() else -1

                    self.associations.append((type1, name1, lower1, upper1, type2, name2, lower2, upper2))

    def generate_sql(self):
        sql_statements = []
        for class_name, attrs in self.classes.items():
            lines = [f'CREATE TABLE `{class_name}` (']
            attr_lines = []
            for attr_name, sql_type in attrs:
                not_null = " NOT NULL" if 'PRIMARY KEY' not in sql_type.upper() else ""
                attr_lines.append(f'  `{attr_name}` {sql_type}{not_null}')
            lines.append(",\n".join(attr_lines))
            lines.append(");")
            sql_statements.append("\n".join(lines))

        for (t1, n1, l1, u1, t2, n2, l2, u2) in self.associations:
            c1 = self.class_ids.get(t1)
            c2 = self.class_ids.get(t2)
            if not c1 or not c2:
                continue

            many_to_many = (u1 == -1 and u2 == -1) or (u1 == -1 and u2 > 1) or (u2 == -1 and u1 > 1)
            one_to_many = ((u1 == 1 and (u2 == -1 or u2 > 1)) or (u2 == 1 and (u1 == -1 or u1 > 1)))

            if many_to_many:
                join_table = f'{c1}_{c2}_join'
                lines = [f'CREATE TABLE `{join_table}` (']
                lines.append(f'  `{c1.lower()}_id` INT NOT NULL,')
                lines.append(f'  `{c2.lower()}_id` INT NOT NULL,')
                lines.append(f'  PRIMARY KEY (`{c1.lower()}_id`, `{c2.lower()}_id`),')
                lines.append(f'  FOREIGN KEY (`{c1.lower()}_id`) REFERENCES `{c1}`(`id`),')
                lines.append(f'  FOREIGN KEY (`{c2.lower()}_id`) REFERENCES `{c2}`(`id`)')
                lines.append(");")
                sql_statements.append("\n".join(lines))

            elif one_to_many:
                if u1 == 1:
                    fk_table = c2
                    fk_col = f'{n1}_id' if n1 else f'{c1.lower()}_id'
                    ref_table = c1
                else:
                    fk_table = c1
                    fk_col = f'{n2}_id' if n2 else f'{c2.lower()}_id'
                    ref_table = c2

                sql_statements.append(f'ALTER TABLE `{fk_table}` ADD COLUMN `{fk_col}` INT;')
                sql_statements.append(
                    f'ALTER TABLE `{fk_table}` ADD FOREIGN KEY (`{fk_col}`) REFERENCES `{ref_table}`(`id`);'
                )
            else:
                fk_table = c1
                fk_col = f'{n2}_id' if n2 else f'{c2.lower()}_id'
                ref_table = c2
                sql_statements.append(f'ALTER TABLE `{fk_table}` ADD COLUMN `{fk_col}` INT;')
                sql_statements.append(
                    f'ALTER TABLE `{fk_table}` ADD FOREIGN KEY (`{fk_col}`) REFERENCES `{ref_table}`(`id`);'
                )
        return sql_statements

def generate_sql_from_uml_content(xml_content):
    parser = UMLParser(xml_content)
    parser.parse_classes()
    parser.parse_associations()
    sql_code = parser.generate_sql()
    return "\n\n".join(sql_code)

# --- SQL Script to UML (Original) ---
def generate_uml_from_sql(sql_input):
    sql = sqlparse.format(sql_input, strip_comments=True).strip()
    statements = sqlparse.split(sql)

    model = ET.Element('uml:Model', {
        'xmlns:xmi': XMI_NAMESPACE,
        'xmlns:uml': UML_NAMESPACE,
        'xmi:version': '2.1',
        'name': 'SQLToUML'
    })

    class_map = {}  # table_name -> xmi:id

    # First pass: create UML classes
    for stmt in statements:
        parsed = sqlparse.parse(stmt)[0]
        tokens = [t for t in parsed.tokens if not t.is_whitespace]

        if len(tokens) < 3:
            continue

        if tokens[0].ttype is sqlparse.tokens.DDL and tokens[0].value.upper() == 'CREATE' and \
           tokens[1].ttype is sqlparse.tokens.Keyword and tokens[1].value.upper() == 'TABLE':
            
            table_name = tokens[2].get_name().strip('`')
            class_id = f'id_{table_name}'
            class_map[table_name] = class_id

            class_elem = ET.SubElement(model, 'packagedElement', {
                'xmi:type': 'uml:Class',
                'xmi:id': class_id,
                'name': table_name
            })

            for t in parsed.tokens:
                if t.is_group:
                    columns_def = t.value.strip('()')
                    col_defs = re.split(r',\s*(?![^()]*\))', columns_def)
                    for col_def in col_defs:
                        parts = col_def.strip().split()
                        if len(parts) >= 2 and parts[0].upper() != 'FOREIGN':
                            col_name = parts[0].strip('`')
                            col_type = parts[1].upper()
                            if 'INT' in col_type:
                                uml_type = 'Integer'
                            elif 'CHAR' in col_type or 'TEXT' in col_type or 'VARCHAR' in col_type:
                                uml_type = 'String'
                            elif 'FLOAT' in col_type or 'DOUBLE' in col_type or 'REAL' in col_type:
                                uml_type = 'Float'
                            elif 'BOOLEAN' in col_type:
                                uml_type = 'Boolean'
                            elif 'DATE' in col_type:
                                uml_type = 'Date'
                            else:
                                uml_type = 'String'

                            ET.SubElement(class_elem, 'ownedAttribute', {
                                'xmi:id': f'id_{table_name}_{col_name}',
                                'name': col_name,
                                'type': uml_type
                            })

    # Second pass: create associations based on FOREIGN KEYs
    assoc_count = 1
    for stmt in statements:
        stmt_upper = stmt.upper()
        if 'FOREIGN KEY' in stmt_upper and 'REFERENCES' in stmt_upper:
            match = re.search(r'ALTER TABLE [`"]?(\w+)[`"]?\s+ADD FOREIGN KEY\s+\([`"]?(\w+)[`"]?\)\s+REFERENCES\s+[`"]?(\w+)[`"]?\s*\([`"]?(\w+)[`"]?\)', stmt, re.IGNORECASE)
            if match:
                src_table, src_col, ref_table, ref_col = match.groups()
                if src_table in class_map and ref_table in class_map:
                    assoc_id = f'assoc_{assoc_count}'
                    assoc_count += 1
                    assoc_elem = ET.SubElement(model, 'packagedElement', {
                        'xmi:type': 'uml:Association',
                        'xmi:id': assoc_id
                    })

                    ET.SubElement(assoc_elem, 'ownedEnd', {
                        'xmi:id': f'e{assoc_count}a',
                        'type': class_map[ref_table],
                        'name': ref_table.lower(),
                        'lower': '1',
                        'upper': '1'
                    })

                    ET.SubElement(assoc_elem, 'ownedEnd', {
                        'xmi:id': f'e{assoc_count}b',
                        'type': class_map[src_table],
                        'name': src_table.lower(),
                        'lower': '0',
                        'upper': '-1'
                    })

    # Return pretty XML string
    rough_string = ET.tostring(model, encoding='utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

# --- UML to SQL Schema XML (New) ---
class UMLSchemaParser(UMLParser):
    def generate_sql_xml(self):
        # Create root element for SQL schema XML
        database = ET.Element('database')
        
        # Create tables from classes
        for class_name, attrs in self.classes.items():
            table = ET.SubElement(database, 'table', name=class_name)
            for attr_name, sql_type in attrs:
                # Extract primary key and nullable info
                is_primary = 'PRIMARY KEY' in sql_type.upper()
                is_nullable = 'NOT NULL' not in sql_type.upper() and not is_primary
                col_type = re.sub(r'\sPRIMARY\s+KEY|\sNOT\s+NULL', '', sql_type, flags=re.IGNORECASE)
                
                ET.SubElement(table, 'column', {
                    'name': attr_name,
                    'type': col_type,
                    'primaryKey': str(is_primary).lower(),
                    'nullable': str(is_nullable).lower()
                })
        
        # Create associations
        for (t1, n1, l1, u1, t2, n2, l2, u2) in self.associations:
            c1 = self.class_ids.get(t1)
            c2 = self.class_ids.get(t2)
            if not c1 or not c2:
                continue

            many_to_many = (u1 == -1 and u2 == -1) or (u1 == -1 and u2 > 1) or (u2 == -1 and u1 > 1)
            one_to_many = ((u1 == 1 and (u2 == -1 or u2 > 1)) or (u2 == 1 and (u1 == -1 or u1 > 1)))

            if many_to_many:
                # Create join table for many-to-many
                join_table = f'{c1}_{c2}_join'
                table = ET.SubElement(database, 'table', name=join_table)
                
                # First column
                col1_name = f'{c1.lower()}_id'
                ET.SubElement(table, 'column', {
                    'name': col1_name,
                    'type': 'INT',
                    'primaryKey': 'true',
                    'nullable': 'false'
                })
                
                # Foreign key for first column
                fk1 = ET.SubElement(table, 'foreignKey', targetTable=c1)
                ET.SubElement(fk1, 'reference', {
                    'localColumn': col1_name,
                    'foreignColumn': 'id'
                })
                
                # Second column
                col2_name = f'{c2.lower()}_id'
                ET.SubElement(table, 'column', {
                    'name': col2_name,
                    'type': 'INT',
                    'primaryKey': 'true',
                    'nullable': 'false'
                })
                
                # Foreign key for second column
                fk2 = ET.SubElement(table, 'foreignKey', targetTable=c2)
                ET.SubElement(fk2, 'reference', {
                    'localColumn': col2_name,
                    'foreignColumn': 'id'
                })
                
            else:
                # Determine which table gets the foreign key
                if one_to_many:
                    if u1 == 1:
                        fk_table = c2
                        fk_col = f'{n1}_id' if n1 else f'{c1.lower()}_id'
                        ref_table = c1
                    else:
                        fk_table = c1
                        fk_col = f'{n2}_id' if n2 else f'{c2.lower()}_id'
                        ref_table = c2
                else:
                    fk_table = c1
                    fk_col = f'{n2}_id' if n2 else f'{c2.lower()}_id'
                    ref_table = c2
                
                # Find the table element to add FK to
                for table in database.findall('table'):
                    if table.get('name') == fk_table:
                        # Add column
                        ET.SubElement(table, 'column', {
                            'name': fk_col,
                            'type': 'INT',
                            'primaryKey': 'false',
                            'nullable': 'true'
                        })
                        
                        # Add foreign key
                        fk = ET.SubElement(table, 'foreignKey', targetTable=ref_table)
                        ET.SubElement(fk, 'reference', {
                            'localColumn': fk_col,
                            'foreignColumn': 'id'
                        })
                        break
        
        # Convert to pretty XML string
        rough_string = ET.tostring(database, 'utf-8')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")

def generate_sql_xml_from_uml_content(xml_content):
    parser = UMLSchemaParser(xml_content)
    parser.parse_classes()
    parser.parse_associations()
    return parser.generate_sql_xml()

# --- SQL Schema XML to UML (New) ---
def generate_uml_from_sql_xml(sql_xml_content):
    # Parse SQL XML to UML model
    root = ET.fromstring(sql_xml_content)
    
    # Create UML root element
    model = ET.Element('uml:Model', {
        'xmlns:xmi': XMI_NAMESPACE,
        'xmlns:uml': UML_NAMESPACE,
        'xmi:version': '2.1',
        'name': 'SQLToUML'
    })
    
    # Map for tracking class IDs
    class_map = {}
    class_count = 1
    assoc_count = 1
    
    # First pass: create UML classes from tables
    for table in root.findall('table'):
        table_name = table.get('name')
        class_id = f'class_{class_count}'
        class_count += 1
        class_map[table_name] = class_id
        
        # Create class element
        class_elem = ET.SubElement(model, 'packagedElement', {
            'xmi:type': 'uml:Class',
            'xmi:id': class_id,
            'name': table_name
        })
        
        # Add columns as attributes
        for column in table.findall('column'):
            col_name = column.get('name')
            col_type = column.get('type')
            
            # Map SQL type to UML type
            if 'INT' in col_type or 'BIGINT' in col_type:
                uml_type = 'Integer'
            elif 'CHAR' in col_type or 'TEXT' in col_type or 'VARCHAR' in col_type:
                uml_type = 'String'
            elif 'FLOAT' in col_type or 'DOUBLE' in col_type or 'REAL' in col_type:
                uml_type = 'Float'
            elif 'BOOLEAN' in col_type:
                uml_type = 'Boolean'
            elif 'DATE' in col_type:
                uml_type = 'Date'
            else:
                uml_type = 'String'
                
            ET.SubElement(class_elem, 'ownedAttribute', {
                'xmi:id': f'attr_{class_id}_{col_name}',
                'name': col_name,
                'type': uml_type
            })
    
    # Second pass: create associations from foreign keys
    for table in root.findall('table'):
        table_name = table.get('name')
        source_class_id = class_map.get(table_name)
        
        for fk in table.findall('foreignKey'):
            target_table = fk.get('targetTable')
            target_class_id = class_map.get(target_table)
            
            if not source_class_id or not target_class_id:
                continue
                
            # Create association element
            assoc_id = f'assoc_{assoc_count}'
            assoc_count += 1
            assoc_elem = ET.SubElement(model, 'packagedElement', {
                'xmi:type': 'uml:Association',
                'xmi:id': assoc_id
            })
            
            # Find reference column
            ref = fk.find('reference')
            if ref is None:
                continue
                
            # Create association ends
            ET.SubElement(assoc_elem, 'ownedEnd', {
                'xmi:id': f'{assoc_id}_end1',
                'type': target_class_id,
                'name': f'{target_table.lower()}_ref',
                'lower': '1',
                'upper': '1'
            })
            
            ET.SubElement(assoc_elem, 'ownedEnd', {
                'xmi:id': f'{assoc_id}_end2',
                'type': source_class_id,
                'name': f'{table_name.lower()}_ref',
                'lower': '0',
                'upper': '-1'
            })
    
    # Return pretty XML string
    rough_string = ET.tostring(model, encoding='utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

# --- Streamlit UI and styling ---
st.set_page_config(page_title="Bidirectional UML/SQL Converter", layout="centered")

# Custom CSS styling
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(135deg, #facfd1, #c2e9fb);
        min-height: 100vh;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        color: #1e4d8f;
        padding: 1rem 2rem;
    }
    .title {
        font-size: 2.5rem;
        font-family: "Chalkduster", "fantasy", cursive;
        font-weight: 700;
        color: #1e4d8f;
        text-align: center;
        margin-bottom: 1rem;
        text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.1);
    }
    .description {
        font-size: 1rem;
        font-weight: 500;
        text-align: center;
        margin-bottom: 2rem;
        color: #1e4d8f;
    }

    button, .stButton>button {
        background-color: #ff90b3;
        color: #1e4d8f;
        font-weight: 700;
        font-size: 1.1rem;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        transition: all 0.3s ease;
        border: none;
        cursor: pointer;
        margin-top: 1rem;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    button:hover, .stButton>button:hover {
        background-color: #e86a94;
        color: white;
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
    }
    textarea {
        border-radius: 8px;
        border: 2px solid #1e4d8f;
        padding: 0.75rem;
        font-family: Consolas, monospace;
        font-size: 1rem;
        color: #1e4d8f;
        background-color: rgba(255, 255, 255, 0.8);
        width: 100%;
        min-height: 200px;
        transition: border-color 0.3s;
    }
    textarea:focus {
        border-color: #ff90b3;
        outline: none;
    }
    .stTabs [role="tablist"] {
        background-color: rgba(255, 255, 255, 0.7);
        border-radius: 8px;
        padding: 0.5rem;
        margin-bottom: 1rem;
    }
    .stTabs [role="tab"][aria-selected="true"] {
        background-color: #ff90b3;
        color: white;
        font-weight: bold;
        border-radius: 6px;
    }
    .stTabs [role="tab"] {
        transition: all 0.3s ease;
    }
    .stTabs [role="tab"]:hover {
        background-color: #e86a94;
        color: white;
    }
    .stAlert {
        border-radius: 8px;
    }
    .stCodeBlock {
        border-radius: 8px;
        border: 1px solid #1e4d8f;
        background-color: rgba(255, 255, 255, 0.9);
        padding: 1rem;
        margin-top: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="title">Bidirectional UML & SQL Converter</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="description">Convert between UML models and SQL schemas using different formats</div>',
    unsafe_allow_html=True,
)

tab1, tab2, tab3, tab4 = st.tabs([
    "UML → SQL Script", 
    "SQL Script → UML", 
    "UML → SQL Schema (XML)", 
    "SQL Schema (XML) → UML"
])

with tab1:
    st.markdown('<div class="tab-container">', unsafe_allow_html=True)
    st.header("Convert UML (XMI 2.1) to SQL DDL Script")
    
    uml_file1 = st.file_uploader("Upload UML XML file (XMI 2.1)", type=["xml", "xmi"], key="uml_file1")
    if uml_file1 is not None:
        uml_input1 = uml_file1.read().decode("utf-8")
    else:
        uml_input1 = st.text_area("Or paste your UML XML here:", height=300, key="uml_text1")

    if st.button("Convert UML to SQL Script", key="btn1"):
        if not uml_input1.strip():
            st.error("Please provide UML XML content (upload or paste).")
        else:
            try:
                sql_output = generate_sql_from_uml_content(uml_input1)
                st.code(sql_output, language="sql")
                st.download_button("Download SQL File", sql_output, file_name="schema.sql", key="dl1")
            except Exception as e:
                st.error(f"Error during conversion: {e}")
    st.markdown('</div>', unsafe_allow_html=True)

with tab2:
    st.markdown('<div class="tab-container">', unsafe_allow_html=True)
    st.header("Convert SQL DDL Script to UML (XMI 2.1)")
    
    sql_file2 = st.file_uploader("Upload SQL file (.sql)", type=["sql", "txt"], key="sql_file2")
    if sql_file2 is not None:
        sql_input2 = sql_file2.read().decode("utf-8")
    else:
        sql_input2 = st.text_area("Or paste your SQL DDL statements here:", height=300, key="sql_text2")

    if st.button("Convert SQL Script to UML", key="btn2"):
        if not sql_input2.strip():
            st.error("Please provide SQL DDL content (upload or paste).")
        else:
            try:
                uml_output = generate_uml_from_sql(sql_input2)
                st.code(uml_output, language="xml")
                st.download_button("Download UML XML", uml_output, file_name="uml_model.xmi", key="dl2")
            except Exception as e:
                st.error(f"Error during conversion: {e}")
    st.markdown('</div>', unsafe_allow_html=True)

with tab3:
    st.markdown('<div class="tab-container">', unsafe_allow_html=True)
    st.header("Convert UML (XMI 2.1) to SQL Schema XML")
    
    uml_file3 = st.file_uploader("Upload UML XML file (XMI 2.1)", type=["xml", "xmi"], key="uml_file3")
    if uml_file3 is not None:
        uml_input3 = uml_file3.read().decode("utf-8")
    else:
        uml_input3 = st.text_area("Or paste your UML XML here:", height=300, key="uml_text3")

    if st.button("Convert UML to SQL Schema XML", key="btn3"):
        if not uml_input3.strip():
            st.error("Please provide UML XML content (upload or paste).")
        else:
            try:
                sql_xml_output = generate_sql_xml_from_uml_content(uml_input3)
                st.code(sql_xml_output, language="xml")
                st.download_button("Download SQL Schema XML", sql_xml_output, file_name="sql_schema.xml", key="dl3")
            except Exception as e:
                st.error(f"Error during conversion: {e}")
    st.markdown('</div>', unsafe_allow_html=True)

with tab4:
    st.markdown('<div class="tab-container">', unsafe_allow_html=True)
    st.header("Convert SQL Schema XML to UML (XMI 2.1)")
    
    sql_xml_file = st.file_uploader("Upload SQL Schema XML file", type=["xml"], key="sql_xml_file")
    if sql_xml_file is not None:
        sql_xml_input = sql_xml_file.read().decode("utf-8")
    else:
        sql_xml_input = st.text_area("Or paste your SQL Schema XML here:", height=300, key="sql_xml_text")

    if st.button("Convert SQL Schema to UML", key="btn4"):
        if not sql_xml_input.strip():
            st.error("Please provide SQL Schema XML content (upload or paste).")
        else:
            try:
                uml_output = generate_uml_from_sql_xml(sql_xml_input)
                st.code(uml_output, language="xml")
                st.download_button("Download UML XML", uml_output, file_name="uml_model.xmi", key="dl4")
            except Exception as e:
                st.error(f"Error during conversion: {e}")
    st.markdown('</div>', unsafe_allow_html=True)