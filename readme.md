# UML ↔ SQL Bidirectional Converter

This is a Streamlit-based tool for converting between UML diagrams (in XMI 2.1 format), SQL DDL scripts, and SQL schema XML. It provides a browser-based UI for transforming models in both directions.

---

## Features

- **Four Conversion Modes**:
  - UML (XMI 2.1) → SQL DDL Script
  - SQL DDL Script → UML (XMI 2.1)
  - UML (XMI 2.1) → SQL Schema XML
  - SQL Schema XML → UML (XMI 2.1)
  
- **Support for Multiple Relationship Types**:
  - One-to-One
  - One-to-Many
  - Many-to-Many

- **User-Friendly Interface**:
  - File upload or direct text input
  - Syntax-highlighted output
  - Downloadable results
  - Responsive design

## Requirements

- Python 3.8 or higher
- Required packages:
  - `streamlit`
  - `sqlparse`
  - `xml.etree.ElementTree` (standard library)
  - `xml.dom.minidom` (standard library)


### Install dependencies:

```bash
pip install streamlit sqlparse

### To Run Application:

```in terminal 
streamlit run app.py

