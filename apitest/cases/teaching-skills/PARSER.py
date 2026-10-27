import unittest
from teaching_models import parse_skill, ValidationError, set_skill_enabled

SOURCE='名称：数学解题引导\n适用条件：方程,去括号\n资料：数学\n工具：knowledge_search\n启用：是\n\n先问学生的思路。'

class SkillParserTests(unittest.TestCase):
    def test_optional_fields_comments_crlf_and_source_preserved(self):
        source='\ufeff# 注释\r\n\r\n名称:测试\r\n适用条件:Equation；方程\r\n启用:否\r\n\r\n引导正文'
        result=parse_skill(source)
        self.assertEqual(result['source_text'],source);self.assertEqual(result['enabled'],0);self.assertEqual(result['tools_json'],'[]')
        self.assertEqual(parse_skill(set_skill_enabled(source,True))['enabled'],1)

    def test_all_length_boundaries(self):
        for key,limit in [('名称',32),('适用条件',120),('资料',32)]:
            import re
            source=re.sub(key+'：[^\n]*',key+'：'+'字'*limit,SOURCE)
            parse_skill(source)
            with self.assertRaises(ValidationError):parse_skill(source.replace('字'*limit,'字'*(limit+1)))
        source=SOURCE.split('\n\n')[0]+'\n\n'+'字'*2000
        parse_skill(source)
        with self.assertRaises(ValidationError):parse_skill(source+'字')
        source='#'+'x'*(8000-len(SOURCE)-2)+'\n'+SOURCE
        self.assertEqual(len(source),8000)
        parse_skill(source)
        with self.assertRaises(ValidationError):parse_skill(source+'x')

    def test_metadata_validation_and_tools(self):
        for source in ['',None,[],SOURCE.replace('名称：数学解题引导','名称：'),SOURCE.replace('启用：是','启用：是\n工具：knowledge_search'),SOURCE.replace('工具：knowledge_search','工具：knowledge_search,other'),SOURCE.replace('工具：knowledge_search','工具：other'),SOURCE.replace('名称：数学解题引导','随便一行')]:
            with self.subTest(source=repr(source)[:60]):
                with self.assertRaises(ValidationError):parse_skill(source)
