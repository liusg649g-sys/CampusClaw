"""Deterministic tools, no file/network/process access and no code evaluation."""
import ast
from decimal import Decimal, InvalidOperation, localcontext
import json
import math
import operator


class InvalidArguments(ValueError): pass
class ToolFailure(ValueError): pass


UNITS = {
    'mm':('length','0.001','0'), 'cm':('length','0.01','0'),
    'm':('length','1','0'), 'km':('length','1000','0'),
    'mg':('mass','0.000001','0'), 'g':('mass','0.001','0'), 'kg':('mass','1','0'),
    'ms':('time','0.001','0'), 's':('time','1','0'), 'min':('time','60','0'), 'h':('time','3600','0'),
}


def schema(properties, required):
    return {'type':'object','properties':properties,'required':required,'additionalProperties':False}


DEFINITIONS = [
    {'name':'formula_hint','description':'根据问题给出公式或解题步骤提示，不计算最终数值答案；支持去括号、方程、面积和速度。',
     'inputSchema':schema({'query':{'type':'string','minLength':1,'maxLength':500}},['query'])},
    {'name':'calculator','description':'安全计算有限十进制表达式，支持 + - * / 与括号和一元正负号；不支持函数、幂、变量。最多200字符、64个AST节点、深度16、绝对值不超过1e12。',
     'inputSchema':schema({'expression':{'type':'string','minLength':1,'maxLength':200,'pattern':r'^[0-9. +*/()\-]+$'}},['expression'])},
    {'name':'unit_convert','description':'确定性长度、质量、时间单位换算，返回数值、目标单位及换算规则；不支持跨维度换算。',
     'inputSchema':schema({'value':{'type':'number','minimum':-1e12,'maximum':1e12},
        'from_unit':{'type':'string','enum':list(UNITS)},'to_unit':{'type':'string','enum':list(UNITS)}},['value','from_unit','to_unit'])},
]


def validate(arguments, definition):
    spec=definition['inputSchema']
    if not isinstance(arguments,dict) or set(arguments)-set(spec['properties']) or set(spec['required'])-set(arguments):
        raise InvalidArguments('参数缺失或包含未声明字段')
    for key,value in arguments.items():
        field=spec['properties'][key]
        if field['type']=='string':
            if not isinstance(value,str) or not value.strip() or not field.get('minLength',1)<=len(value)<=field.get('maxLength',1000):
                raise InvalidArguments('字符串参数类型或长度无效')
            if 'enum' in field and value not in field['enum']: raise InvalidArguments('不支持的单位')
        else:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or abs(value)>1e12:
                raise InvalidArguments('数值必须是范围内的有限数字')


def calculate(expression):
    import re
    if not re.fullmatch(r'[0-9. +*/()\-]+',expression): raise InvalidArguments('表达式含非法字符')
    depth=0
    for char in expression:
        if char=='(':depth+=1
        elif char==')':depth-=1
        if depth>16 or depth<0:raise InvalidArguments('括号嵌套过深或不匹配')
    if depth:raise InvalidArguments('括号不匹配')
    try: tree=ast.parse(expression.strip(),mode='eval')
    except (SyntaxError,ValueError,RecursionError): raise InvalidArguments('表达式格式无效') from None
    if sum(1 for _ in ast.walk(tree))>64: raise InvalidArguments('表达式过于复杂')
    binary={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}
    def visit(node,depth=0):
        if depth>16: raise InvalidArguments('表达式嵌套过深')
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):
            try: result=Decimal(ast.get_source_segment(expression.strip(),node))
            except InvalidOperation: raise InvalidArguments('数值格式无效') from None
        elif isinstance(node,ast.BinOp) and type(node.op) in binary:
            left,right=visit(node.left,depth+1),visit(node.right,depth+1)
            if isinstance(node.op,ast.Div) and right==0: raise ToolFailure('不能除以零')
            result=binary[type(node.op)](left,right)
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            result=visit(node.operand,depth+1)*(-1 if isinstance(node.op,ast.USub) else 1)
        else: raise InvalidArguments('不支持的表达式操作')
        if not result.is_finite() or abs(result)>Decimal('1e12'): raise ToolFailure('计算结果或中间值超出范围')
        return result
    with localcontext() as context:
        context.prec=32
        return {'value':float(visit(tree.body))}


def invoke(name, arguments):
    definition=next((d for d in DEFINITIONS if d['name']==name),None)
    if definition is None: raise InvalidArguments('工具不存在')
    validate(arguments,definition)
    if name=='calculator': return calculate(arguments['expression'])
    if name=='formula_hint':
        query=arguments['query'].casefold()
        hints=[('括号','去括号时，括号前的系数应乘到括号内每一项；逐项检查符号。'),
               ('方程','对等式两边执行相同运算；先合并同类项，再思考如何隔离未知数。'),
               ('面积','先辨认图形：长方形面积为长乘宽，三角形面积为底乘高再除以二。'),
               ('速度','先统一长度和时间单位，再用速度等于路程除以时间分析。')]
        return {'hint':next((hint for word,hint in hints if word in query),'先列出已知条件和目标，再检查单位与可用公式；每次只推进一步。')}
    left,right=UNITS[arguments['from_unit']],UNITS[arguments['to_unit']]
    if left[0]!=right[0]: raise ToolFailure('单位类型不兼容，不能换算')
    with localcontext() as context:
        context.prec=32
        factor=Decimal(left[1])/Decimal(right[1])
        value=Decimal(str(arguments['value']))*factor
        if abs(value)>Decimal('1e12'): raise ToolFailure('换算结果超出范围')
        return {'value':float(value),'unit':arguments['to_unit'],'factor':float(factor)}


def call_result(name, arguments):
    try:
        data=invoke(name,arguments)
        return {'content':[{'type':'text','text':json.dumps(data,ensure_ascii=False,allow_nan=False)}],'isError':False}
    except ToolFailure as error:
        return {'content':[{'type':'text','text':str(error)}],'isError':True}
