"""Test improvements to CEL syntax highlighting"""

import pytest
from koreo_tooling.indexing.cel_semantics import lex, parse, KEYWORDS
from koreo_tooling.indexing.semantics import Position


class TestCELLexerImprovements:
    """Test the enhanced CEL lexer"""
    
    def test_float_number_parsing(self):
        """Test parsing of floating point numbers"""
        tokens = lex(["3.14159"], seed_line=0, seed_offset=0)
        assert len(tokens) == 1
        assert tokens[0].text == "3.14159"
        assert tokens[0].token_type == "number"
        
    def test_scientific_notation_parsing(self):
        """Test parsing of scientific notation"""
        tokens = lex(["1.23e-4"], seed_line=0, seed_offset=0)
        assert len(tokens) == 1
        assert tokens[0].text == "1.23e-4"
        assert tokens[0].token_type == "number"
        
    def test_new_operators(self):
        """Test new operators like / and %"""
        tokens = lex(["10 / 2 % 3"], seed_line=0, seed_offset=0)
        # Should be: 10, /, 2, %, 3
        non_space_tokens = [t for t in tokens if t.token_type != ""]
        assert len(non_space_tokens) == 5
        assert non_space_tokens[1].text == "/"
        assert non_space_tokens[1].token_type == "operator"
        assert non_space_tokens[3].text == "%"
        assert non_space_tokens[3].token_type == "operator"
        
    def test_enhanced_string_escaping(self):
        """Test improved string handling with escapes"""
        tokens = lex(['"hello\\"world"'], seed_line=0, seed_offset=0)
        # Should handle escaped quotes properly
        assert len(tokens) == 3  # open quote, string content, close quote
        assert tokens[1].text == 'hello\\"world'
        assert tokens[1].token_type == "string"
        
    def test_keyword_recognition(self):
        """Test recognition of additional keywords"""
        for keyword in ["true", "false", "null", "size", "matches"]:
            assert keyword in KEYWORDS
            
    def test_no_equals_found(self):
        """Test handling when no = is found in expression"""
        # Test that the lexer handles expressions without issues
        tokens = lex(["test value without equals"], seed_line=0, seed_offset=0)
        assert len(tokens) > 0
        # Should successfully tokenize even without = character


class TestCELSemanticExtraction:
    """Test semantic node extraction improvements"""
    
    def test_number_token_classification(self):
        """Test that numbers are properly classified"""
        nodes = parse(["42 + 3.14"], Position(0, 0))
        
        # Find number nodes
        number_nodes = [n for n in nodes if n.node_type == "number"]
        assert len(number_nodes) == 2
        assert any(n.length == 2 for n in number_nodes)  # "42"
        assert any(n.length == 4 for n in number_nodes)  # "3.14"
        
    def test_keyword_classification(self):
        """Test that keywords are properly classified"""
        nodes = parse(["true && false || null"], Position(0, 0))
        
        keyword_nodes = [n for n in nodes if n.node_type == "keyword"]
        assert len(keyword_nodes) == 3
        
    def test_function_classification(self):
        """Test that functions are properly classified"""
        nodes = parse(["size(items) + matches(pattern)"], Position(0, 0))
        
        # Keywords 'size' and 'matches' should be classified as keywords, not functions
        keyword_nodes = [n for n in nodes if n.node_type == "keyword"]
        assert len(keyword_nodes) == 2  # size and matches are keywords
        
    def test_variable_classification(self):
        """Test that variables are properly classified"""
        nodes = parse(["inputs.name + parent.id"], Position(0, 0))
        
        variable_nodes = [n for n in nodes if n.node_type == "variable"]
        assert len(variable_nodes) >= 4  # inputs, name, parent, id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])