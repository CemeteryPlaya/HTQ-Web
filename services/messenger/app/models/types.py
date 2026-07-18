"""Custom LtreeType for PostgreSQL."""

import sqlalchemy.types as types

class LtreeType(types.UserDefinedType):
    """PostgreSQL ltree type."""
    
    def get_col_spec(self):
        return "ltree"
    
    def bind_processor(self, dialect):
        def process(value):
            if value is not None:
                return str(value)
            return value
        return process
    
    def result_processor(self, dialect, coltype):
        def process(value):
            if value is not None:
                return str(value)
            return value
        return process
