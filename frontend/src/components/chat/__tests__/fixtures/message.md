# Markdown 渲染验收

## 二级标题
### 三级标题
#### 四级标题
##### 五级标题
###### 六级标题

Setext 标题
----------

一段有 **粗体**、_斜体_、***粗斜体***、~~删除线~~ 和 `a < b` 的文字。转义 \*星号\*，实体 &amp;。

普通换行 A
普通换行 B\
显式换行 C

> 外层引用
>
> > 内层引用含 **强调**。

3. 有序条目
   - 无序子项
4. 第二项

- [x] 已完成
- [ ] 待完成

---

```ts
const literal = '<tag> **not bold**';
const longLine = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
```

~~~text
波浪号围栏
~~~

    缩进代码块

| 左列 | 中列 | 右列 |
| :--- | :---: | ---: |
| a \| b | **通过** | `42` |
| abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 | 无换行长单元格 | 99 |

[行内链接](https://example.com "链接标题")、[引用链接][target]、[相对链接](/docs)、<https://example.org>、https://example.net 和 team@example.com。

[target]: https://example.com/docs

![TraceForge 图标](/favicon.svg "图片标题")

脚注引用[^note]，重复引用[^note]。

[^note]: 脚注正文含 *斜体*。

原样 HTML `<section>` 和 <b data-markdown-example="literal">原样标签</b>。

Markdown 验收结束。
