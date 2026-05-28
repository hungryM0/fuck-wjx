from __future__ import annotations

from wjx.provider.html_parser import parse_survey_questions_from_html


class WjxHtmlParserTests:
    def test_parse_survey_questions_from_html_returns_empty_when_container_missing(self) -> None:
        assert parse_survey_questions_from_html("<html><body><div>无题目</div></body></html>") == []

    def test_parse_survey_questions_from_html_extracts_basic_question_metadata(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="1" id="div1" type="3">
                  <div class="topichtml">1. 本题检测，请选择 非常满意</div>
                  <div class="ui-controlgroup">
                    <div><span class="label">一般</span><img src="https://example.com/opt-a.png" /></div>
                    <div><span class="label">非常满意</span></div>
                  </div>
                </div>
                <div topic="2" id="div2" type="4" relation="1,2">
                  <div class="topichtml">2. 请选择你常用的功能 [至少选1项，最多选2项]<img src="https://example.com/title-q2.png" /></div>
                  <div class="ui-controlgroup">
                    <div><span class="label">功能A</span></div>
                    <div><span class="label">功能B</span></div>
                  </div>
                  <input type="checkbox" jumpto="5" />
                  <input type="checkbox" />
                </div>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        assert len(questions) == 2

        first = questions[0]
        assert first["num"] == 1
        assert first["display_num"] == 1
        assert first["title"] == "本题检测，请选择 非常满意"
        assert first["type_code"] == "3"
        assert first["options"] == 2
        assert first["option_texts"] == ["一般", "非常满意"]
        assert first["forced_option_index"] == 1
        assert first["forced_option_text"] == "非常满意"
        assert first["page"] == 1
        assert first["logic_parse_status"] == "complete"
        assert first["question_media"] == [
            {
                "kind": "image",
                "scope": "option",
                "index": 0,
                "source_url": "https://example.com/opt-a.png",
                "label": "一般",
            }
        ]

        second = questions[1]
        assert second["num"] == 2
        assert second["display_num"] == 2
        assert second["type_code"] == "4"
        assert second["multi_min_limit"] == 1
        assert second["multi_max_limit"] == 2
        assert second["has_jump"]
        assert second["jump_rules"] == [
            {"option_index": 0, "jumpto": 5, "option_text": "功能A", "terminates_survey": False}
        ]
        assert second["has_display_condition"]
        assert second["display_conditions"] == [
            {
                "condition_question_num": 1,
                "condition_mode": "selected",
                "condition_option_indices": [1],
                "raw_relation": "1,2",
            }
        ]
        assert second["logic_parse_status"] == "complete"
        assert second["question_media"] == [
            {
                "kind": "image",
                "scope": "title",
                "index": None,
                "source_url": "https://example.com/title-q2.png",
                "label": "题干图",
            }
        ]

    def test_parse_survey_questions_from_html_extracts_matrix_and_slider_metadata(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="3" id="div3" type="6">
                  <div class="topichtml">3. 请评价以下项目</div>
                  <table id="divRefTab3">
                    <tr id="drv3_1"><td></td><td>差</td><td>好</td></tr>
                    <tr rowindex="1"><td>外观</td><td><input name="q3_1_1" type="radio" /></td><td><input name="q3_1_2" type="radio" /></td></tr>
                    <tr rowindex="2"><td>功能</td><td><input name="q3_2_1" type="radio" /></td><td><input name="q3_2_2" type="radio" /></td></tr>
                  </table>
                </div>
                <div topic="4" id="div4" type="8">
                  <div class="topichtml">4. 请拖动滑块</div>
                  <input id="q4" type="range" min="1" max="5" step="0.5" />
                </div>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        matrix = questions[0]
        assert matrix["num"] == 3
        assert matrix["rows"] == 2
        assert matrix["row_texts"] == ["外观", "功能"]
        assert matrix["option_texts"] == ["差", "好"]
        assert matrix["options"] == 2

        slider = questions[1]
        assert slider["num"] == 4
        assert slider["type_code"] == "8"
        assert slider["options"] == 1
        assert slider["slider_min"] == 1.0
        assert slider["slider_max"] == 5.0
        assert slider["slider_step"] == 0.5

    def test_parse_survey_questions_from_html_marks_description_and_multi_text_cases(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="5" id="div5" type="3">
                  <div class="topichtml">5. 请阅读以下说明</div>
                  <p>这里没有任何选项控件</p>
                </div>
                <div topic="6" id="div6" type="1" gapfill="1">
                  <div class="topichtml">6. 请填写你的信息</div>
                  姓名：<input type="text" />
                  电话：<input type="text" />
                </div>
                <div topic="7" id="div7" type="9" gapfill="1">
                  <div class="topichtml">
                    项目评价<input id="q7_1" style="display:none" type="text" />
                    <label class="textEdit"><span class="textCont" contenteditable="true"></span></label>
                    <div>请输入手机号<input id="q7_2" style="display:none" type="text" />
                    <label class="textEdit"><span class="textCont" contenteditable="true"></span></label></div>
                  </div>
                </div>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        description = questions[0]
        assert description["is_description"]
        assert description["options"] == 0

        multi_text = questions[1]
        assert multi_text["text_inputs"] == 2
        assert multi_text["text_input_labels"] == ["姓名", "电话"]
        assert multi_text["is_multi_text"]
        assert multi_text["is_text_like"]
        assert questions[2]["text_input_labels"] == ["项目评价", "请输入手机号"]

    def test_parse_survey_questions_keeps_internal_num_when_explicit_display_num_matches_visible_order(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="23" id="div23" type="2">
                  <div class="field-label">
                    <span class="req">*</span>
                    <div class="topicnumber">1.</div>
                    <div class="topichtml">请您对培训和实习进行简要评价：<span>（最少30字）</span></div>
                  </div>
                  <textarea id="q23" minword="30" name="q23"></textarea>
                </div>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        assert questions[0]["num"] == 23
        assert questions[0]["display_num"] == 1
        assert questions[0]["title"] == "请您对培训和实习进行简要评价： （最少30字）"

    def test_parse_survey_questions_recalculates_display_num_when_previous_question_is_hidden(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="20" id="div20" type="5" style="display:none;">
                  <div class="field-label">
                    <div class="topicnumber">20.</div>
                    <div class="topichtml">隐藏题</div>
                  </div>
                </div>
                <div topic="21" id="div21" type="4">
                  <div class="field-label">
                    <div class="topicnumber">21.</div>
                    <div class="topichtml">显示题一</div>
                  </div>
                </div>
                <div topic="23" id="div23" type="2">
                  <div class="field-label">
                    <div class="topicnumber">23.</div>
                    <div class="topichtml">显示题二</div>
                  </div>
                  <textarea id="q23" name="q23"></textarea>
                </div>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        assert questions[0]["num"] == 20
        assert questions[0]["display_num"] == 20
        assert questions[1]["num"] == 21
        assert questions[1]["display_num"] == 1
        assert questions[2]["num"] == 23
        assert questions[2]["display_num"] == 2

    def test_parse_survey_questions_treats_hidden_ancestor_question_as_hidden(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <section style="display:none;">
                  <div topic="20" id="div20" type="5">
                    <div class="field-label">
                      <div class="topicnumber">20.</div>
                      <div class="topichtml">隐藏题</div>
                    </div>
                  </div>
                </section>
                <div topic="21" id="div21" type="4">
                  <div class="field-label">
                    <div class="topicnumber">21.</div>
                    <div class="topichtml">显示题一</div>
                  </div>
                  <div class="ui-controlgroup"><div><span class="label">A</span></div></div>
                </div>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        assert questions[0]["display_num"] == 20
        assert questions[1]["display_num"] == 1

    def test_parse_survey_questions_matches_shifted_visible_numbering_after_hidden_question(self) -> None:
        question_blocks = []
        for num in range(1, 20):
            question_blocks.append(
                f"""
                <div topic="{num}" id="div{num}" type="3">
                  <div class="field-label">
                    <div class="topicnumber">{num}.</div>
                    <div class="topichtml">题目{num}</div>
                  </div>
                  <div class="ui-controlgroup"><div><span class="label">A</span></div></div>
                </div>
                """
            )
        question_blocks.append(
            """
            <div topic="20" id="div20" type="5" style="display:none;">
              <div class="field-label">
                <div class="topicnumber">20.</div>
                <div class="topichtml">隐藏题</div>
              </div>
            </div>
            """
        )
        question_blocks.append(
            """
            <div topic="21" id="div21" type="4">
              <div class="field-label">
                <div class="topicnumber">21.</div>
                <div class="topichtml">题目21</div>
              </div>
              <div class="ui-controlgroup"><div><span class="label">A</span></div></div>
            </div>
            """
        )
        question_blocks.append(
            """
            <div topic="22" id="div22" type="3">
              <div class="field-label">
                <div class="topicnumber">22.</div>
                <div class="topichtml">题目22</div>
              </div>
              <div class="ui-controlgroup"><div><span class="label">A</span></div></div>
            </div>
            """
        )
        question_blocks.append(
            """
            <div topic="23" id="div23" type="2">
              <div class="field-label">
                <div class="topicnumber">23.</div>
                <div class="topichtml">题目23</div>
              </div>
              <textarea id="q23" name="q23"></textarea>
            </div>
            """
        )
        html = f"""
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                {''.join(question_blocks)}
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)
        by_num = {item["num"]: item for item in questions}

        assert by_num[20]["display_num"] == 20
        assert by_num[21]["display_num"] == 20
        assert by_num[22]["display_num"] == 21
        assert by_num[23]["display_num"] == 22

    def test_parse_survey_questions_marks_hidden_relation_minus_one_blocks_as_description(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="8" id="div8" style="display:none;" relation="-1" type="1">
                  <div class="field-label">
                    <div class="topicnumber">8.</div>
                    <div class="topichtml">（二）接触渠道与接触频率</div>
                  </div>
                  <div class="ui-input-text">
                    <input type="text" id="q8" name="q8" />
                  </div>
                </div>
                <div topic="9" id="div9" req="1" type="4">
                  <div class="field-label">
                    <span class="req">*</span>
                    <div class="topicnumber">8.</div>
                    <div class="topichtml">您主要通过哪些渠道接触韶山文化相关内容？（可多选）</div>
                  </div>
                  <div class="ui-controlgroup">
                    <div><span class="label">A. 短视频平台</span></div>
                    <div><span class="label">B. 社交平台</span></div>
                  </div>
                </div>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        assert questions[0]["num"] == 8
        assert questions[0]["is_description"]
        assert questions[1]["num"] == 9
        assert questions[1]["display_num"] == 1
        assert not questions[1]["is_description"]

    def test_parse_survey_questions_from_html_falls_back_to_nested_topic_divs_and_slider_matrix(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <section>
                  <div topic="9" id="div9" type="2">
                    <div class="topichtml">9. 位置题</div>
                    <input verify="腾讯地图定位" />
                  </div>
                  <div topic="11" id="div11" type="1">
                    <div class="topichtml">11. 地区题</div>
                    <input type="text" verify="省市区" onclick="openCityBox(this,3,event,1);" readonly="readonly" />
                  </div>
                  <div topic="10" id="div10" type="6">
                    <div class="topichtml">10. 滑块矩阵</div>
                    <tr class="rowtitletr"><td class="title"><span class="itemTitleSpan">体验</span></td></tr>
                    <tr class="rowtitletr"><td class="title"><span class="itemTitleSpan">价格</span></td></tr>
                    <div class="ruler"><span class="cm" data-value="1"></span><span class="cm" data-value="5"></span></div>
                    <input class="ui-slider-input" rowid="1" min="1" max="5" step="1" />
                    <input class="ui-slider-input" rowid="2" min="1" max="5" step="1" />
                    <div class="rangeslider"></div>
                    <div class="rangeslider"></div>
                  </div>
                </section>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        location = questions[0]
        assert location["is_location"]
        assert location["type_code"] == "2"
        assert location["text_inputs"] == 0

        region = questions[1]
        assert region["is_location"]
        assert region["type_code"] == "1"
        assert region["text_inputs"] == 0

        slider_matrix = questions[2]
        assert slider_matrix["is_slider_matrix"]
        assert slider_matrix["slider_min"] == 1.0
        assert slider_matrix["slider_max"] == 5.0
        assert slider_matrix["slider_step"] == 1.0
